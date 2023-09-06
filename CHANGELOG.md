- Handle PrimaryKey as str on Python3

# 0.7.3 (2023-09-02)

- Support updating the author header after the client is initialized.


# 0.7.2 (2023-08-13)

- add DownloadSignalLog


# 0.7.1 (2023-07-27)

- Handle new webstack semantic version format.


# 0.7.0 (2023-06-28)

- Regenerate graph client for new module library APIs.
- Add streaming API to download blobs.
- Set the default pool size to 10 for `UnixSocketConnectionPool`.


# 0.6.1 (2023-07-17)

- Print download directory when downloading scene files.


# 0.6.0 (2023-06-28)

- Support backup encrypted system information for debugging purpose.


# 0.5.0 (2023-04-18)

- Support HTTP over Unix domain socket via optional `unixEndpoint` argument.


# 0.4.1 (2023-03-13)

- Regenerate graph client for new module library APIs.


# 0.4.0 (2023-03-12)

- Add `GetSchema` API.
- Generate graph client for `ListModules` API.


# 0.3.0 (2023-02-15)

- Remove automatic query field generation for graphql api. These fields can be
  changed frequently causing the webstack client to be unusuable. Users of
  graph api now nees to explicitly specify fields and subfields they are
  interested in.


# 0.2.0 (2022-12-01)

- Regenerate graph client for sensorLInkName.


# 0.1.3 (2023-01-18)

- Update GraphQL client.


# 0.1.2 (2023-01-13)

- Bugfix: Require `scenepk` argument in `GetSceneSensorMapping` and `SetSceneSensorMapping`


# 0.1.1 (2023-01-11)

- Update GraphQL client.


# 0.1.0 (2022-11-17)

- Port from mujincontrollerclientpy.
