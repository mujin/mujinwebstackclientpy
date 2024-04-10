# Changelog

## 0.7.9 (2024-04-10)

### Changes

- Add `HeadConfig` API.


## 0.7.8 (2024-03-19)

### Changes

- Regenerate the graph client.


## 0.7.7 (2024-02-29)

### Changes

- Regenerate the graph client.


## 0.7.6 (2023-11-05)

### Changes

- Add a decorator to break large query into a few small queries.
- Update graph client generation algorithm and regenerate the graph client.
- Introduce iterator for large queries.


## 0.7.5 (2023-10-09)

### Changes

- Handle PrimaryKey as str on Python3


## 0.7.4 (2023-09-19)

### Changes

- Add `CreateLogEntries` API and update GraphQL client.
- Fix readme file references to the old repository.


## 0.7.3 (2023-09-02)

### Changes

- Support updating the author header after the client is initialized.


## 0.7.2 (2023-08-13)

### Changes

- Add DownloadSignalLog


## 0.7.1 (2023-07-27)

### Changes

- Handle new webstack semantic version format.


## 0.7.0 (2023-06-28)

### Changes

- Regenerate graph client for new module library APIs.
- Add streaming API to download blobs.
- Set the default pool size to 10 for `UnixSocketConnectionPool`.


## 0.6.1 (2023-06-28)

### Changes

- Print download directory when downloading scene files.


## 0.6.0 (2023-06-28)

### Changes

- Support backup encrypted system information for debugging purpose.


## 0.5.0 (2023-04-18)

### Changes

- Support HTTP over Unix domain socket via optional `unixEndpoint` argument.


## 0.4.1 (2023-03-13)

### Changes

- Regenerate graph client for new module library APIs.


## 0.4.0 (2023-03-12)

### Changes

- Add `GetSchema` API.
- Generate graph client for `ListModules` API.


## 0.3.0 (2023-02-15)

### Changes

- Remove automatic query field generation for graphql api. These fields can be
  changed frequently causing the webstack client to be unusuable. Users of
  graph api now nees to explicitly specify fields and subfields they are
  interested in.


## 0.2.0 (2023-02-15)

### Changes

- Regenerate graph client for sensorLInkName.


## 0.1.3 (2023-01-18)

### Changes

- Update GraphQL client.


## 0.1.2 (2023-01-13)

### Changes

- Bugfix: Require `scenepk` argument in `GetSceneSensorMapping` and `SetSceneSensorMapping`


## 0.1.1 (2023-01-11)

### Changes

- Update GraphQL client.


## 0.1.0 (2022-11-17)

### Changes

- Port from mujincontrollerclientpy.
