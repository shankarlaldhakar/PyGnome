"""
Test if this is how we want id property of
object that inherits from GnomeId to behave
"""

import pytest
import copy

from uuid import uuid1
from gnome.gnomeobject import GnomeId


def test_exceptions():
    with pytest.raises(AttributeError):
        go = GnomeId()
        print '\n id exists: {0}'.format(go.id)  # calls getter, assigns an id
        go.id = uuid1()


def test_copy():
    go = GnomeId()
    go_c = copy.copy(go)
    assert go.id != go_c.id
    assert go is not go_c


def test_deepcopy():
    go = GnomeId()
    go_c = copy.deepcopy(go)
    assert go.id != go_c.id
    assert go is not go_c
