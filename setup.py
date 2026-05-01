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
    license='Apache License, Version 2.0',  # license must be kept in setup.py unless packaging>=24.2 is adopted
    # flake8 compliance configuration
    enable_flake8=True,  # Enable checks
    fail_on_flake=True,  # Fail builds when checks fail
)
