# -*- coding: utf-8 -*-
# Copyright (C) 2012-2014 MUJIN Inc
from setuptools import setup

try:
    from mujincommon.setuptools import Distribution
except (ImportError, SyntaxError):
    from setuptools.dist import Distribution

setup(
    distclass=Distribution,
    locale_dir='locale',
    # flake8 compliance configuration
    enable_flake8=True,  # Enable checks
    fail_on_flake=True,  # Fail builds when checks fail
)
