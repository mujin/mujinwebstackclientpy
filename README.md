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

```bash
PYTHONPATH=python uv run --with six==1.16.0 --with requests==2.27.1 --with graphql-core==3.2.0 --with typing_extensions==4.2.0 devbin/mujin_webstackclientpy_generategraphclient.py --url http://controller123 > python/mujinwebstackclient/webstackgraphclient.py
```
