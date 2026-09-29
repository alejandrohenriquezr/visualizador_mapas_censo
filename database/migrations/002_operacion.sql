CREATE TABLE IF NOT EXISTS deployment_history (
    id BIGSERIAL PRIMARY KEY,
    app_version TEXT,
    git_commit TEXT,
    resultado TEXT NOT NULL,
    detalle JSONB,
    creado_en TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_deployment_history_creado
    ON deployment_history(creado_en DESC);
