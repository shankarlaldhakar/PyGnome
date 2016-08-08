'''
NetCDF outputter - write the nc_particles netcdf file format
'''

import copy
import os
from datetime import datetime

import netCDF4 as nc

import numpy as np

from colander import SchemaNode, String, drop, Int, Bool

from gnome import __version__
from gnome.basic_types import oil_status, world_point_type

from gnome.utilities.serializable import Serializable, Field

from . import Outputter, BaseSchema


# Big dict that stores the attributes for the standard data arrays
# in the output - these are constants. The instance var_attributes are stored
# with the NetCDFOutput object
var_attributes = {
    'time': {'long_name': 'time since the beginning of the simulation',
             'standard_name': 'time',
             'calendar': 'gregorian',
             'standard_name': 'time',
             'comment': 'unspecified time zone',
             # units will get set based on data
             },
    'particle_count': {'units': '1',
                       'long_name': 'number of particles in a given timestep',
                       'ragged_row_count': 'particle count at nth timestep',
                       },
    'longitude': {'long_name': 'longitude of the particle',
                  'standard_name': 'longitude',
                  'units': 'degrees_east',
                  },
    'latitude': {'long_name': 'latitude of the particle',
                 'standard_name': 'latitude',
                 'units': 'degrees_north',
                 },
    'depth': {'long_name': 'particle depth below sea surface',
              'standard_name': 'depth',
              'units': 'meters',
              'axis': 'z positive down',
              },
    'mass': {'long_name': 'mass of particle',
             'units': 'kilograms',
             },
    'age': {'long_name': 'age of particle from time of release',
            'units': 'seconds',
            },
    'status_codes': {
        'long_name': 'particle status code',
        'flag_values': " ".join(["%i" % i for i in oil_status._int]),
        'flag_meanings': " ".join(["%i: %s," % pair for pair in
                                   sorted(zip(oil_status._int,
                                              oil_status._attr))])
                      },
    'spill_num': {'long_name': 'spill to which the particle belongs'},
    'id': {'long_name': 'particle ID',
           },
    'droplet_diameter': {'long_name': 'diameter of oil droplet class',
                         'units': 'meters'
                         },
    'rise_vel': {'long_name': 'rise velocity of oil droplet class',
                              'units': 'm s-1'},
    'next_positions': {},
    'last_water_positions': {},

    # weathering data
    'floating': {
        'long_name': 'total mass floating in water after each time step',
        'units': 'kilograms'},
    'evaporated': {
        'long_name': 'total mass evaporated since beginning of model run',
        'units': 'kilograms'},
    'dispersed': {
        'long_name': 'total mass dispersed since beginning of model run',
        'units': 'kilograms'},
    'avg_density': {
        'long_name': 'average density at end of timestep',
        'units': 'kg/m^3'},
    'avg_viscosity': {
        'long_name': 'average viscosity at end of timestep',
        'units': 'kg/m^3'},
    'amount_released': {
        'long_name': 'total mass of oil released thus far',
        'units': 'kg'},
}


class NetCDFOutputSchema(BaseSchema):
    'colander schema for serialize/deserialize object'
    netcdf_filename = SchemaNode(String(), missing=drop)
    all_data = SchemaNode(Bool(), missing=drop)
    compress = SchemaNode(Bool(), missing=drop)
    _start_idx = SchemaNode(Int(), missing=drop)
    _middle_of_run = SchemaNode(Bool(), missing=drop)


class NetCDFOutput(Outputter, Serializable):
    """
    A NetCDFOutput object is used to write the model's data to a NetCDF file.
    It inherits from Outputter class and implements the same interface.

    This class is meant to be used within the Model, to be added to list of
    outputters.

    >>> model = gnome.model.Model(...)
    >>> model.outputters += gnome.netcdf_outputter.NetCDFOutput(
                os.path.join(base_dir,'sample_model.nc'), which_data='most')

    `which_data` flag is used to set which data to add to the netcdf file:

    'standard' : the basic stuff most people would want

    'most': everything the model is tracking except the internal-use-only arrays

    'all': everything tracked by the model (mostly used for diagnostics of save files)


    .. note::
       cf_attributes is a class attribute: a dict
       that contains the global attributes per CF convention

       The attribute: `.arrays_to_output` is a set of the data arrays that
       will be added to the netcdf file. array names may be added to or removed
       from this set before a model run to customize what gets output:
       `the_netcdf_outputter.arrays_to_output.add['rise_vel']`

       Since some of the names of the netcdf variables are different from the
       names in the SpillContainer data_arrays, this list uses the netcdf names
    """
    which_data_lu = {'standard', 'most', 'all'}
    compress_lu = {True, False}

    cf_attributes = {'comment': 'Particle output from the NOAA PyGnome model',
                     'source': 'PyGnome version {0}'.format(__version__),
                     'references': 'TBD',
                     'feature_type': 'particle_trajectory',
                     'institution': 'NOAA Emergency Response Division',
                     'conventions': 'CF-1.6',
                     }

    # the set of arrays we usually output -- i.e. the default
    standard_arrays = ['latitude',
                       'longitude',  # pulled from the 'positions' array
                       'depth',
                       'status_codes',
                       'spill_num',
                       'id',
                       'mass',
                       'age',
                       ]

    # the list of arrays that we usually don't want -- i.e. for internal use
    # these will get skipped if "most" is asked for
    # "all" will output everything.
    usually_skipped_arrays = ['next_positions',
                              'last_water_positions',
                              'windages',
                              'windage_range',
                              'windage_persist',
                              'mass_components',
                              'half_lives',
                              ]

    # define _state for serialization
    _state = copy.deepcopy(Outputter._state)

    # data file should not be moved to save file location!
    _state.add_field([Field('netcdf_filename', save=True, update=True,
                            test_for_eq=False),
                      Field('which_data', save=True, update=True),
                      # Field('netcdf_format', save=True, update=True),
                      Field('compress', save=True, update=True),
                      Field('_start_idx', save=True),
                      Field('_middle_of_run', save=True),
                      ])
    _schema = NetCDFOutputSchema

    def __init__(self,
                 netcdf_filename,
                 which_data='standard',
                 compress=True,
                 **kwargs):
        """
        Constructor for Net_CDFOutput object. It reads data from cache and
        writes it to a NetCDF4 format file using the CF convention

        :param netcdf_filename: Required parameter. The filename in which to
            store the NetCDF data.
        :type netcdf_filename: str. or unicode

        :param which_data='standard':
            If 'standard', write only standard data.
            If 'most' means, write everything except the attributes we know are
            for internal model use.
            If 'all', write all data to NetCDF -- usually only for diagnostics.
            Default is 'standard'.
            These are defined in the standard_arrays and usually_skipped_arrays
            attributes
        :type which_data: string -- one of {'standard', 'most', 'all'}

        Optional arguments passed on to base class (kwargs):

        :param cache: sets the cache object from which to read data. The model
            will automatically set this param

        :param output_timestep: default is None in which case every time the
            write_output is called, output is written. If set, then output is
            written every output_timestep starting from model_start_time.
        :type output_timestep: timedelta object

        :param output_zero_step: default is True. If True then output for
            initial step (showing initial release conditions) is written
            regardless of output_timestep
        :type output_zero_step: boolean

        :param output_last_step: default is True. If True then output for
            final step is written regardless of output_timestep
        :type output_last_step: boolean

        use super to pass optional kwargs to base class __init__ method
        """
        self._check_filename(netcdf_filename)
        self._netcdf_filename = netcdf_filename

        # uncertain file is only written out if model is uncertain
        name, ext = os.path.splitext(self.netcdf_filename)
        self._u_netcdf_filename = '{0}_uncertain{1}'.format(name, ext)

        self.name = os.path.split(netcdf_filename)[1]

        # flag to keep track of _state of the object - is True after calling
        # prepare_for_model_run
        self._middle_of_run = False

        if which_data.lower() in self.which_data_lu:
            self._which_data = which_data.lower()
        else:
            raise ValueError('which_data must be one of: '
                             '{"standard", "most", "all"}')

        self.arrays_to_output = set(self.standard_arrays)

        # this is only updated in prepare_for_model_run if which_data is
        # 'all' or 'most'
        # self.arr_types = None
        self._format = 'NETCDF4'

        if compress in self.compress_lu:
            self._compress = compress
        else:
            raise ValueError('compress must be one of: {True, False}')

        # 1k is about right for 1000LEs and one time step.
        # up to 0.5MB tested better for large datasets, but
        # we don't want to have far-too-large files for the
        # smaller ones
        # The default in netcdf4 is 1 -- which works really badly
        self._chunksize = 1024

        # need to keep track of starting index for writing data since variable
        # number of particles are released
        self._start_idx = 0

        # define NetCDF variable attributes that are instance attributes here
        # It is set in prepare_for_model_run():
        # 'spill_names' is set based on the names of spill's as defined by user
        # time 'units' are seconds since model_start_time
        self._var_attributes = {
            'spill_num': {'spills_map': ''},
            'time': {'units': ''}
                                 }

        super(NetCDFOutput, self).__init__(**kwargs)

    @property
    def middle_of_run(self):
        return self._middle_of_run

    @property
    def netcdf_filename(self):
        return self._netcdf_filename

    @netcdf_filename.setter
    def netcdf_filename(self, new_name):
        if self.middle_of_run:
            raise AttributeError('This attribute cannot be changed in the '
                                 'middle of a run')
        else:
            self._check_netcdf_filename(new_name)
            self._netcdf_filename = new_name

    @property
    def uncertain_filename(self):
        '''
        if uncertain SpillContainer is present, write its data out to this file
        '''
        return self._u_netcdf_filename

    @property
    def which_data(self):
        return self._which_data

    @which_data.setter
    def which_data(self, value):
        'change output data but cannot change in middle of run.'
        if value == self._which_data:
            return
        if self.middle_of_run:
            raise AttributeError('This attribute cannot be changed in the '
                                 'middle of a run')

        if value in self.which_data_lu:
            self._which_data = value
        else:
            raise ValueError('which_data must be one of: '
                             '{"standard", "most", "all"}')

    @property
    def chunksize(self):
        return self._chunksize

    @chunksize.setter
    def chunksize(self, value):
        if self.middle_of_run:
            raise AttributeError('chunksize can not be set '
                                 'in the middle of a run')
        else:
            self._chunksize = value

    @property
    def compress(self):
        return self._compress

    @compress.setter
    def compress(self, value):
        if self.middle_of_run:
            raise AttributeError('This attribute cannot be changed in the '
                                 'middle of a run')

        if value in self.compress_lu:
            self._compress = value
        else:
            raise ValueError('compress must be one of: {True, False}')

    @property
    def netcdf_format(self):
        return self._format

    def _update_var_attributes(self, spills):
        '''
        update instance specific self._var_attributes
        '''
        names = " ".join(["{0}: {1}, ".format(ix, spill.name)
                          for ix, spill in enumerate(spills)])
        self._var_attributes['spill_num']['spills_map'] = names
        self._var_attributes['time']['units'] = \
            ('seconds since {0}').format(self._model_start_time.isoformat())

    def _initialize_rootgrp(self, rootgrp, sc):
        'create dimensions for root group and set cf_attributes'
        # fixme: why remove the "T" ??
        rootgrp.setncatts(self.cf_attributes)   # class level attributes
        rootgrp.setncattr('creation_date',  # instance attribute
                          datetime.now().replace(microsecond=0).isoformat())

        # array sizes of weathering processes + mass_components will vary
        # depending on spills. If there are no spills then no weathering
        # data arrays to write - certainly no data to write
        weathering_sz = None

        # create the dimensions we need
        # not sure if it's a convention or if dimensions
        # need to be names...
        dims = [('time', None),     # unlimited
                ('data', None),     # unlimited
                ('two', 2),
                ('three', 3)]

        if 'mass_components' in sc:
            # get it from array shape
            weathering_sz = (sc.num_released, sc['mass_components'].shape[1])
            dims.append(('weathering', weathering_sz[1]))

        for dim in dims:
            rootgrp.createDimension(dim[0], dim[1])

        return rootgrp

    def _update_arrays_to_output(self, sc):
        'create list of variables that we want to put in the file'
        if self.which_data in ('all', 'most'):
            # get shape and dtype from initailized numpy arrays instead
            # of array_types because some array type shapes are None
            for var_name in sc.data_arrays:
                if var_name != 'positions':
                    # handled by latitude, longitude, depth
                    self.arrays_to_output.add(var_name)

            if self.which_data == 'most':
                # remove the ones we don't want
                for var_name in self.usually_skipped_arrays:
                    self.arrays_to_output.discard(var_name)

    def prepare_for_model_run(self,
                              model_start_time,
                              spills,
                              **kwargs):
        """
        .. function:: prepare_for_model_run(model_start_time,
                                            spills,
                                            **kwargs)

        Write global attributes and define dimensions and variables for NetCDF file.
        This must be done in prepare_for_model_run because if model _state
        changes, it is rewound and re-run from the beginning.

        If there are existing output files, they are deleted here.

        This takes more than standard 'cache' argument. Some of these are
        required arguments - they contain None for defaults because non-default
        argument cannot follow default argument. Since cache is already 2nd
        positional argument for Renderer object, the required non-default
        arguments must be defined following 'cache'.

        If uncertainty is on, then SpillContainerPair object contains
        identical _data_arrays in both certain and uncertain SpillContainers,
        the data itself is different, but they contain the same type of data
        arrays. If uncertain, then datay arrays for uncertain spill container
        are written to netcdf_filename + '_uncertain.nc'

        :param spills: If 'which_data' flag is set to 'all' or 'most', then
            model must provide the model.spills object
            (SpillContainerPair object) so NetCDF variables can be
            defined for the remaining data arrays.
            If spills is None, but which_data flag is 'all' or
            'most', a ValueError will be raised.
            It does not make sense to write 'all' or 'most' but not
            provide 'model.spills'.
        :type spills: gnome.spill_container.SpillContainerPair object.

        .. note::
            Does not take any other input arguments; however, to keep the
            interface the same for all outputters, define ``**kwargs`` in case
            future outputters require different arguments.

        use super to pass model_start_time, cache=None and
        remaining kwargs to base class method
        """
        super(NetCDFOutput, self).prepare_for_model_run(model_start_time,
                                                        spills, **kwargs)
        if not self.on: 
            return

        self.clean_output_files()

        self._update_var_attributes(spills)

        for sc in self.sc_pair.items():
            if sc.uncertain:
                file_ = self._u_netcdf_filename
            else:
                file_ = self.netcdf_filename

            self._file_exists_error(file_)

            # create the netcdf files and write the standard stuff:
            with nc.Dataset(file_, 'w', format=self._format) as rootgrp:

                self._initialize_rootgrp(rootgrp, sc)

                # create a dict with dims {2: 'two', 3: 'three' ...}
                # use this to define the NC variable's shape in code below
                d_dims = {len(dim): name
                          for name, dim in rootgrp.dimensions.iteritems()
                          if len(dim) > 0}

                # create the time/particle_count variables
                self._create_nc_var(rootgrp, 'time', np.float64,
                                    ('time', ), (self._chunksize,))
                self._create_nc_var(rootgrp, 'particle_count', np.int32,
                                    ('time', ), (self._chunksize,))

                self._update_arrays_to_output(sc)

                for var_name in self.arrays_to_output:
                    # the special cases:
                    if var_name in ('latitude', 'longitude', 'depth'):
                        # these don't  map directly to an array_type
                        dt = world_point_type
                        shape = ('data', )
                        chunksz = (self._chunksize,)
                    else:
                        # in prepare_for_model_run, nothing is released but
                        # numpy arrays are initialized with 0 elements so use
                        # the arrays to get shape and dtype instead of the
                        # array_types since array_type could contain None for
                        # shape
                        dt = sc[var_name].dtype

                        if len(sc[var_name].shape) == 1:
                            shape = ('data',)
                            chunksz = (self._chunksize,)
                        else:
                            y_sz = d_dims[sc[var_name].shape[1]]
                            shape = ('data', y_sz)
                            chunksz = (self._chunksize, sc[var_name].shape[1])

                    self._create_nc_var(rootgrp, var_name, dt, shape, chunksz)

                # Add subgroup for mass_balance - could do it w/o subgroup
                if sc.mass_balance:
                    grp = rootgrp.createGroup('mass_balance')
                    # give this grp a dimension for time
                    grp.createDimension('time', None)  # unlimited
                    for key in sc.mass_balance:
                        self._create_nc_var(grp,
                                            var_name=key,
                                            dtype='float',
                                            shape=('time',),
                                            chunksz=(256,),
                                            # smaller chunksize for mass_balance
                                            )

        # need to keep track of starting index for writing data since variable
        # number of particles are released
        self._start_idx = 0
        self._middle_of_run = True

    def _create_nc_var(self, grp, var_name, dtype, shape, chunksz):
        # fixme: why is this even here? it's wrapping a single call???
        if dtype == np.bool:
            # this is not primitive so it is not understood
            # Make it 8-bit unsigned - numpy stores True/False in 1 byte
            dtype = 'u1'

        try:
            if var_name != "non_weathering":
                # fixme: TOTAL Kludge --
                # failing with bad chunksize error for this particular varaible
                # I have no idea why!!!!
                var = grp.createVariable(var_name,
                                         dtype,
                                         shape,
                                         zlib=self._compress,
                                         chunksizes=chunksz,
                                         )
            else:
                var = grp.createVariable(var_name,
                                         dtype,
                                         shape,
                                         zlib=self._compress,
                                         )
        except RuntimeError as err:
            msg = "\narguments are:"
            msg += "var_name: %s\n" % var_name
            msg += "dtype: %s\n" % dtype
            msg += "shape: %s\n" % shape
            msg += "dims: %s\n" % grp.dimensions
            # msg += "shape_dim: %s\n" % grp.dimensions[shape[0]]
            msg += "zlib: %s\n" % self._compress
            msg += "chunksizes: %s\n" % chunksz
            err.args = (err.args[0] + msg,)
            raise err

        if var_name in var_attributes:
            var.setncatts(var_attributes[var_name])

        if var_name in self._var_attributes:
            var.setncatts(self._var_attributes[var_name])

        return var

    def write_output(self, step_num, islast_step=False):
        """
        Write NetCDF output at the end of the step

        :param int step_num: the model step number you want rendered.
        :param bool islast_step: Default is False.
                                 Flag that indicates that step_num is
                                 last step.
                                 If 'output_last_step' is True then this is
                                 written out

        Use super to call base class write_output method
        """
        super(NetCDFOutput, self).write_output(step_num, islast_step)

        if self.on is False or not self._write_step:
            return None

        for sc in self.cache.load_timestep(step_num).items():
            if sc.uncertain and self._u_netcdf_filename is not None:
                file_ = self._u_netcdf_filename
            else:
                file_ = self.netcdf_filename

            time_stamp = sc.current_time_stamp

            with nc.Dataset(file_, 'a') as rootgrp:
                rg_vars = rootgrp.variables
                idx = len(rg_vars['time'])

                rg_vars['time'][idx] = nc.date2num(time_stamp,
                                                   rg_vars['time'].units,
                                                   rg_vars['time'].calendar)
                pc = rg_vars['particle_count']
                pc[idx] = len(sc)

                _end_idx = self._start_idx + pc[idx]

                # add the data:
                for var_name in self.arrays_to_output:
                    # special case positions:
                    if var_name == 'longitude':
                        rg_vars['longitude'][self._start_idx:_end_idx] = sc['positions'][:, 0]
                    elif var_name == 'latitude':
                        rg_vars['latitude'][self._start_idx:_end_idx] = sc['positions'][:, 1]
                    elif var_name == 'depth':
                        rg_vars['depth'][self._start_idx:_end_idx] = sc['positions'][:, 2]
                    else:
                        rg_vars[var_name][self._start_idx:_end_idx] = sc[var_name]

                # write mass_balance data
                if sc.mass_balance:
                    grp = rootgrp.groups['mass_balance']
                    for key, val in sc.mass_balance.iteritems():
                        if key not in grp.variables:
                            self._create_nc_var(grp,
                                                key, 'float', ('time', ),
                                                (self._chunksize,)
                                                )
                        grp.variables[key][idx] = val

        self._start_idx = _end_idx  # set _start_idx for the next timestep

        return {'netcdf_filename': (self.netcdf_filename,
                                    self._u_netcdf_filename),
                'time_stamp': time_stamp}

    def clean_output_files(self):
        '''
        deletes output files that may be around

        called by prepare_for_model_run

        here in case it needs to be called from elsewhere
        '''
        try:
          os.remove(self.netcdf_filename)
        except OSError:
            pass # it must not be there
        try:
            os.remove(self._u_netcdf_filename)
        except OSError:
            pass # it must not be there

    def rewind(self):
        '''
        reset a few parameter and call base class rewind to reset
        internal variables.
        '''
        super(NetCDFOutput, self).rewind()

        self._middle_of_run = False
        self._start_idx = 0

    @classmethod
    def read_data(klass,
                  netcdf_file,
                  time=None,
                  index=None,
                  which_data='standard'):
        """
        Read and create standard data arrays for a netcdf file that was created
        with NetCDFOutput class. Make it a class method since it is
        independent of an instance of the Outputter. The method is put with
        this class because the NetCDF functionality for PyGnome data with CF
        standard is captured here.

        :param str netcdf_file: Name of the NetCDF file from which to read
            the data
        :param datetime time: timestamp at which the data is desired. Looks in
            the netcdf data's 'time' array and finds the closest time to this
            and outputs this data. If both 'time' and 'index' are None, return
            data if file only contains one 'time' else raise an error
        :param int index: Index of the 'time' variable (or time_step). This is
            only used if 'time' is None. If both 'time' and 'index' are None,
            return data if file only contains one 'time' else raise an error
        :param which_data='standard': Which data arrays are desired options are
            ('standard', 'most', 'all', [list_of_array_names])
        :type which_data: string or sequence of strings.

        :return: A dict containing standard data closest to the indicated
            'time'. Standard data is defined as follows:

        Standard data arrays are numpy arrays of size N, where N is number of
        particles released at time step of interest. They are defined by the
        class attribute "standard_arrays", currently:

            'current_time_stamp': datetime object associated with this data
            'positions'         : NX3 array. NetCDF variables: 'longitude', 'latitude', 'depth'
            'status_codes'      : NX1 array. NetCDF variable :'status_codes'
            'spill_num'         : NX1 array. NetCDF variable: 'spill_num'
            'id'                : NX1 array of particle id. NetCDF variable 'id'
            'mass'              : NX1 array showing 'mass' of each particle

        standard_arrays = ['latitude',
                           'longitude', # pulled from the 'positions' array
                           'depth',
                           'status_codes',
                           'spill_num',
                           'id',
                           'mass',
                           'age',
                           ]

        """
        if not os.path.exists(netcdf_file):
            raise IOError('File not found: {0}'.format(netcdf_file))

        arrays_dict = {}
        with nc.Dataset(netcdf_file) as data:
            _start_ix = 0

            # first find the index of index in which we are interested
            time_ = data.variables['time']
            if time is None and index is None:
                # there should only be 1 time in file. Read and
                # return data associated with it
                if len(time_) > 1:
                    raise ValueError('More than one time found in netcdf '
                                     'file. Please specify time/index for '
                                     'which data is desired')
                else:
                    index = 0
            else:
                if time is not None:
                    time_offset = nc.date2num(time, time_.units,
                                              calendar=time_.calendar)
                    if time_offset < 0:
                        'desired time is before start of model'
                        index = 0
                    else:
                        index = abs(time_[:] - time_offset).argmin()
                elif index is not None:
                    if index < 0:
                        index = len(time_) + index

            for idx in range(index):
                _start_ix += data.variables['particle_count'][idx]

            _stop_ix = _start_ix + data.variables['particle_count'][index]
            elem = data.variables['particle_count'][index]

            c_time = nc.num2date(time_[index], time_.units,
                                 calendar=time_.calendar)

            arrays_dict['current_time_stamp'] = np.array(c_time)

            # figure out what arrays to read in:
            if which_data == 'standard':
                data_arrays = set(klass.standard_arrays)
                # swap out positions:
                [data_arrays.discard(x)
                 for x in ('latitude', 'longitude', 'depth')]
                data_arrays.add('positions')
            elif which_data == 'all':
                # pull them from the nc file
                data_arrays = set(data.variables.keys())
                # remove the irrelevant ones:
                [data_arrays.discard(x) for x in ('time',
                                                  'particle_count',
                                                  'latitude',
                                                  'longitude',
                                                  'depth')]
                data_arrays.add('positions')
            else:  # should be list of data arrays
                data_arrays = set(which_data)

            # get the data
            for array_name in data_arrays:
                # special case time and positions:
                if array_name == 'positions':
                    positions = np.zeros((elem, 3), dtype=world_point_type)
                    positions[:, 0] = \
                        data.variables['longitude'][_start_ix:_stop_ix]
                    positions[:, 1] = \
                        data.variables['latitude'][_start_ix:_stop_ix]
                    positions[:, 2] = \
                        data.variables['depth'][_start_ix:_stop_ix]

                    arrays_dict['positions'] = positions
                else:
                    arrays_dict[array_name] = \
                        data.variables[array_name][_start_ix:_stop_ix]

            # get mass_balance
            weathering_data = {}
            if 'mass_balance' in data.groups:
                mb = data.groups['mass_balance']
                for key, val in mb.variables.iteritems():
                    'assume SI units'
                    weathering_data[key] = val[index]

        return (arrays_dict, weathering_data)

    def save(self, saveloc, references=None, name=None):
        '''
        See baseclass :meth:`~gnome.persist.Savable.save`

        update netcdf_filename to point to saveloc, then call base class save
        using super
        '''
        json_ = self.serialize('save')
        fname = os.path.split(json_['netcdf_filename'])[1]
        json_['netcdf_filename'] = os.path.join('./', fname)
        return self._json_to_saveloc(json_, saveloc, references, name)

    @classmethod
    def loads(cls, json_data, saveloc, references=None):
        '''
        loads object from json_data

        update path to 'netcdf_filename' in json_data, then finish loading
        by calling super class' load method

        :param saveloc: location of data files. Setup path of netcdf_filename
            to this location

        Optional parameter

        :param references: references object - if this is called by the Model,
            it will pass a references object. It is not required.
        '''
        json_data['netcdf_filename'] = \
            os.path.join(saveloc, json_data['netcdf_filename'])

        return super(NetCDFOutput, cls).loads(json_data, saveloc, references)
