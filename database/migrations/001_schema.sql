CREATE TABLE IF NOT EXISTS consultas_aprobadas (
    id BIGSERIAL PRIMARY KEY,
    pregunta_limpia TEXT NOT NULL UNIQUE,
    pregunta_original TEXT NOT NULL,
    sql_texto TEXT NOT NULL,
    tabla TEXT,
    variable TEXT,
    operacion TEXT,
    motor_version TEXT,
    creado_en TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    actualizado_en TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    usos BIGINT NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS resultados_consulta (
    consulta_id BIGINT PRIMARY KEY REFERENCES consultas_aprobadas(id) ON DELETE CASCADE,
    respuesta JSONB NOT NULL,
    actualizado_en TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS resultados_pendientes (
    id TEXT PRIMARY KEY,
    pregunta TEXT NOT NULL,
    sql_texto TEXT,
    respuesta JSONB NOT NULL,
    creado_en TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ultimo_acceso TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_resultados_pendientes_creado ON resultados_pendientes(creado_en);

CREATE TABLE IF NOT EXISTS feedback (
    id BIGSERIAL PRIMARY KEY,
    feedback_id TEXT NOT NULL,
    valor TEXT NOT NULL CHECK (valor IN ('positivo','negativo')),
    creado_en TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_feedback_feedback_id ON feedback(feedback_id);
