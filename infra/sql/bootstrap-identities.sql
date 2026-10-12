-- Run as the configured Entra SQL administrator AFTER application migrations.
-- SQLCMD SID variables contain managed identity CLIENT IDs, not principal object IDs.
-- SQL ARM administrator assignments use principal object IDs instead.
-- SID-based external users avoid granting the SQL server Graph directory access.
SET XACT_ABORT ON;
BEGIN TRANSACTION;

DECLARE @api_sid varbinary(16) = CONVERT(varbinary(16), CONVERT(uniqueidentifier, '$(API_CLIENT_ID)'));
DECLARE @ingestion_sid varbinary(16) = CONVERT(varbinary(16), CONVERT(uniqueidentifier, '$(INGESTION_CLIENT_ID)'));
DECLARE @sql nvarchar(max);
IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = 'aiflux-api')
BEGIN
    SET @sql = N'CREATE USER [aiflux-api] WITH SID = ' + CONVERT(nvarchar(34), @api_sid, 1) + N', TYPE = E';
    EXEC sp_executesql @sql;
END;
IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = 'aiflux-ingestion')
BEGIN
    SET @sql = N'CREATE USER [aiflux-ingestion] WITH SID = ' + CONVERT(nvarchar(34), @ingestion_sid, 1) + N', TYPE = E';
    EXEC sp_executesql @sql;
END;
IF EXISTS (SELECT 1 FROM sys.database_principals WHERE name = 'aiflux-api' AND sid <> @api_sid)
    THROW 51000, 'Existing API database user has a different identity SID.', 1;
IF EXISTS (SELECT 1 FROM sys.database_principals WHERE name = 'aiflux-ingestion' AND sid <> @ingestion_sid)
    THROW 51001, 'Existing ingestion database user has a different identity SID.', 1;

-- No DDL permissions: migrations must use a separate reviewed operator identity.
GRANT SELECT, INSERT, UPDATE, DELETE ON SCHEMA::dbo TO [aiflux-api];
GRANT SELECT ON OBJECT::dbo.team_subscriptions TO [aiflux-ingestion];
GRANT SELECT ON OBJECT::dbo.model_prices TO [aiflux-ingestion];
GRANT SELECT, INSERT, UPDATE ON OBJECT::dbo.usage_records TO [aiflux-ingestion];
GRANT SELECT, INSERT, UPDATE ON OBJECT::dbo.ingestion_state TO [aiflux-ingestion];
GRANT SELECT, INSERT, UPDATE ON OBJECT::dbo.safety_events TO [aiflux-ingestion];
COMMIT;
