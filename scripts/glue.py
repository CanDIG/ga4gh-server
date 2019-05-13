"""
Glue to enable script access to candig packages
"""
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

import os
import sys
# the following two lines are the same ones as in dev_glue.py
# they enable python to find the candig.server package
import candig
candig.__path__.insert(0, 'candig')


def ga4ghImportGlue():
    """
    Call this method before importing a candig module in the scripts dir.
    Otherwise, you will be using the installed package instead of
    the development package.
    Assumes a certain directory structure.
    """
    path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.append(path)
