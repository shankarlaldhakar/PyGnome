import gnome.basic_types
import gnome.movers
import numpy

from wtforms import (
    SelectField,
    IntegerField,
    FloatField,
    BooleanField,
    ValidationError,
    FieldList,
    FormField,
    StringField
)

from wtforms.validators import Required, NumberRange, Optional

from webgnome.model_manager import WebWindMover
from webgnome import util
from base import AutoIdForm, DateTimeForm


class WindForm(AutoIdForm, DateTimeForm):
    """
    A specific value in a :class:`gnome.movers.WindMover` time series.
    Note that this class inherits the ``date``, ``hour`` and ``minute`` fields.
    """
    SPEED_KNOTS = 'knots'
    SPEED_METERS = 'meters'
    SPEED_MILES = 'miles'

    SPEED_CHOICES = (
        (SPEED_KNOTS, 'Knots'),
        (SPEED_METERS, 'Meters / sec'),
        (SPEED_MILES, 'Miles / hour')
        )

    speed = FloatField('Speed', default=0, validators=[NumberRange(min=1)])
    speed_type = SelectField(
        choices=SPEED_CHOICES,
        validators=[Required()],
        default=SPEED_KNOTS
    )

    direction = StringField(validators=[Required()])

    def __init__(self, *args, **kwargs):
        super(WindForm, self).__init__(*args, **kwargs)

        self.date.validators = [Optional()]
        self.hour.validators = [Optional()]
        self.minute.validators = [Optional()]

    def _validate_degrees_true(self, direction):
        if 0 > direction > 360:
            raise ValidationError(
                'Direction in degrees true must be between 0 and 360.')

    def _validate_cardinal_direction(self, direction):
        if not util.DirectionConverter.is_cardinal_direction(direction):
            raise ValidationError(
                'A cardinal directions must be one of: %s' % ', '.join(
                    util.DirectionConverter.DIRECTIONS))

    def validate_direction(self, field):
        try:
            self._validate_degrees_true(float(field.data))
        except ValueError:
            self._validate_cardinal_direction(field.data.upper())

    def get_direction_degree(self):
        """
        Convert user input for direction into degree.
        """
        direction = self.direction.data

        if direction.isalpha():
            return util.DirectionConverter.get_degree(direction)
        else:
            return direction


class WindMoverForm(AutoIdForm):
    """
    A form class representing a :class:`gnome.mover.WindMover` object.
    """
    SCALE_RADIANS = 'rad'
    SCALE_DEGREES = 'deg'

    SCALE_CHOICES = (
        (SCALE_RADIANS, 'rad'),
        (SCALE_DEGREES, 'deg')
    )

    name = StringField(default='Wind Mover', validators=[Required()])
    timeseries = FieldList(FormField(WindForm), min_entries=1)

    is_active = BooleanField('Active', default=True)
    uncertain_speed_scale = FloatField('Speed Scale', default=2,
                               validators=[NumberRange(min=0)])
    uncertain_angle_scale = FloatField('Total Angle Scale', default=0.4,
                                   validators=[NumberRange(min=0)])
    uncertain_angle_scale_type = SelectField(
        default=SCALE_RADIANS,
        choices=SCALE_CHOICES,
        validators=[Required()]
    )

    uncertain_time_delay = FloatField('Start Time', default=0,
        validators=[NumberRange(min=0)])
    uncertain_duration = FloatField('Duration', default=3,
        validators=[NumberRange(min=0)])

    is_constant = BooleanField('Is Constant', default=True)

    auto_increment_time_by = IntegerField('Auto-increment time by', default=6)

    def __init__(self, *args, **kwargs):
        """
        Include an extra field in ``timeseries`` for use as the "Add" form when
        displaying an update form for an object. Do this by taking the length
        of timeseries values passed in from an ``obj`` argument and adding one
        to it.

        ``timeseries.min_entries`` remains the default value if the form is
        receiving a POST.
        """
        super(WindMoverForm, self).__init__(*args, **kwargs)

        obj = kwargs.get('obj', None)
        formdata = args[0] if args else None

        if obj and obj.timeseries and not formdata:
            self.timeseries.append_entry()

    def get_timeseries_ndarray(self):
        num_timeseries = len(self.timeseries)
        timeseries = numpy.zeros((num_timeseries,),
            dtype=gnome.basic_types.datetime_value_2d)

        for idx, time_form in enumerate(self.timeseries):
            direction = time_form.get_direction_degree()
            datetime = time_form.get_datetime()
            timeseries['time'][idx] = datetime
            timeseries['value'][idx] = (time_form.speed.data, direction,)

        return timeseries
    
    def create(self):
        """
        Create a new :class:`WebWindMover` using data from this form.
        """
        return WebWindMover(
            name=self.name.data,
            is_constant=self.is_constant.data,
            is_active=self.is_active.data,
            uncertain_angle_scale=self.uncertain_angle_scale.data,
            uncertain_speed_scale=self.uncertain_speed_scale.data,
            uncertain_duration=self.uncertain_duration.data,
            uncertain_time_delay=self.uncertain_time_delay.data,
            timeseries=self.get_timeseries_ndarray())

    def update(self, mover):
        """
        Update ``mover`` using data from this form.
        """
        mover.is_active = self.is_active.data
        mover.name = self.name.data
        mover.is_constant = self.is_constant.data
        mover.uncertain_angle_scale = self.uncertain_angle_scale.data
        mover.uncertain_speed_scale = self.uncertain_speed_scale.data
        mover.uncertain_duration = self.uncertain_duration.data
        mover.uncertain_time_delay = self.uncertain_time_delay.data
        mover.timeseries = self.get_timeseries_ndarray()

        return mover
    

class AddMoverForm(AutoIdForm):
    """
    The initial form used in a multi-step process for adding a mover to the
    user's running model. This step asks the user to choose the type of mover
    to add.
    """
    mover_type = SelectField('Type', choices=(
        (WindMoverForm.get_id(), 'Winds'),
    ))


class DeleteMoverForm(AutoIdForm):
    """
    Delete mover with ``mover_id``. Validates that a mover with that ID exists
    in ``self.model``.

    This is a hidden form submitted via AJAX by the JavaScript client.
    """
    mover_id = IntegerField()

    def __init__(self, model, *args, **kwargs):
        self.model = model
        super(DeleteMoverForm, self).__init__(*args, **kwargs)

    def mover_id_validate(self, field):
        mover_id = field.data

        if mover_id is None or self.model.has_mover_with_id(mover_id) is False:
            raise ValidationError('Mover with that ID does not exist')


mover_form_classes = {
    WebWindMover: WindMoverForm
}
