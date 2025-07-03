# Changelog

## 0.9.11 (2025-07-03)

- Support an optional bodyId parameter when downloading environment.

## 0.9.10 (2025-06-26)

- Raise WebStack client errors with a copy of the response content instead of the implicit iterator to allow caller to deserialize the content as many times as needed.

## 0.9.9 (2025-06-19)

### Changes

- Add startedAt and endedAt parameters to debug resource APIs.

## 0.9.8 (2025-06-17)

### Changes

- Allow choose queries/mutation/subscription explicitly.

## 0.9.7 (2025-06-05)

### Changes

- Generate GraphQL subscription methods based on WebStack GraphQL schema.

## 0.9.6 (2025-06-04)

### Changes

- Re-generate graph api.

## 0.9.5 (2025-05-27)

### Changes

- Initialize the event loop inside the dedicated thread to avoid clashing with other event loop in the main thread.

## 0.9.4 (2025-05-24)

### Changes

- Add optional parameter to download resolved environments through file download.

## 0.9.3 (2025-05-13)

### Changes

- Regenerate the graph client.
- Rename "application" to "webapp".

## 0.9.2 (2025-04-04)

### Changes

- Regenerate the graph client.

## 0.9.1 (2025-04-04)

### Changes

- Fix typing annotation.

## 0.9.0 (2025-03-28)

### Changes

- Add support for GraphQL subscriptions.

## 0.8.7 (2025-03-27)

### Changes

- Remove suffixes from archive file correctly

## 0.8.6 (2025-02-06)

### Changes

- Regenerate the graph client.

## 0.8.5 (2024-12-23)

### Changes

- Regenerate the graph client.

## 0.8.4 (2024-12-06)

### Changes

- Login through json web token automatically when a token is available.

## 0.8.3 (2024-11-08)

### Changes

- Added options to backup/restore iodd

## 0.8.2 (2024-07-05)

### Changes

- Added downloadSizeLimit parameter to the DownloadDebugResource function.

## 0.8.1 (2024-07-04)

### Changes

- Regenerate the graph client.

## 0.8.0 (2024-06-21)

### Changes

- Support `GetWebStackState`.

## 0.7.11 (2024-06-14)

### Changes

- Allow customizing headers in `CallGraphAPI` calls.

## 0.7.10 (2024-04-11)

### Changes

- Remove `CreateCycleLogs`.

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
  changed frequently causing the webstack client to be unusable. Users of
  graph api now need to explicitly specify fields and subfields they are
  interested in.


## 0.2.0 (2023-02-15)

### Changes

- Regenerate graph client for sensorLinkName.


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
