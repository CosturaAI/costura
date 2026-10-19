-- Runs once, on first start of an empty data volume (docker-entrypoint-initdb.d).
-- Creates the database used by `just api::test`; the app database comes from POSTGRES_DB.
CREATE DATABASE costura_test;
