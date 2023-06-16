# Mujin Controller Python Client Library

![Build status](https://github.com/mujin/mujinwebstackclientpy/actions/workflows/python.yml/badge.svg)

This is an open-source client library communicating with the Mujin Controller WebAPI.


## Releases and Versioning

- The latest stable build is managed by the **master** branch, please use it. It is tested on Linux with Python 3.9.

- Versions have three numbers: MAJOR.MINOR.PATCH
  
  - All versions with the same MAJOR.MINOR number have the same API ande are ABI compatible.


## Running on Linux

Load mujinwebstackclient as a module in Python.


## Install on Linux

```bash
pip install .
```

## Licenses

Mujin Controller Python Client is Licensed under the Apache License, Version 2.0 (the "License"). See [LICENSE](LICENSE)

## For developers

### How to re-generate `webstackgraphclient.py`

First, set up a virtualenv to install required pip packages:

```bash
# create a new virtualenv, you can also delete it afterwards
virtualenv .ve

# install required packages
./.ve/bin/pip install six==1.16.0 requests==2.27.1 graphql-core==3.2.0 typing_extensions==4.2.0

# install mujinwebstackclient
./.ve/bin/pip install .
```

Then, use `mujin_webstackclientpy_generategraphclient.py` to generate the content of the `webstackgraphclient.py` file.

```bash
./.ve/bin/python devbin/mujin_webstackclientpy_generategraphclient.py --url http://controller123 > python/mujinwebstackclient/webstackgraphclient.py
```

## Troubleshooting

### Jhbuild fails due to flake8:
If Jhbuild fails on building mujinwebstackclientpy due to a flake8 violation (most likely with a several hundred errors and warnings), this could be happening due to flake8 running a default configuration within a virtual environment.

If this seems to be the case, you can delete the virtual environment.
```bash
# delete the virtual environment
rm -rf ./.ve
```