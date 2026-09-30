CREATE TABLE IF NOT EXISTS aprendizaje_consultas (
    id TEXT PRIMARY KEY,
    session_id TEXT,
    feedback_id TEXT,
    pregunta TEXT NOT NULL,
    pregunta_normalizada TEXT,
    contexto JSONB NOT NULL DEFAULT '{}'::jsonb,
    resultado TEXT NOT NULL DEFAULT 'iniciada'
        CHECK (resultado IN ('iniciada','exito','ambiguedad','error','cancelada')),
    tipo_ambiguedad TEXT,
    opciones_ambiguedad INTEGER,
    interpretacion JSONB,
    senales JSONB,
    riesgo_sombra DOUBLE PRECISION,
    cache_aprobada BOOLEAN NOT NULL DEFAULT FALSE,
    feedback_valor TEXT CHECK (feedback_valor IS NULL OR feedback_valor IN ('positivo','negativo')),
    excel_descargado BOOLEAN NOT NULL DEFAULT FALSE,
    reformulacion_probable BOOLEAN NOT NULL DEFAULT FALSE,
    reformulacion_similitud DOUBLE PRECISION,
    reformulada_por TEXT,
    error_codigo INTEGER,
    error_detalle TEXT,
    iniciado_en TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finalizado_en TIMESTAMPTZ,
    actualizado_en TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_aprendizaje_session_fecha
    ON aprendizaje_consultas(session_id, iniciado_en DESC);
CREATE INDEX IF NOT EXISTS idx_aprendizaje_feedback
    ON aprendizaje_consultas(feedback_id);
CREATE INDEX IF NOT EXISTS idx_aprendizaje_resultado_fecha
    ON aprendizaje_consultas(resultado, iniciado_en DESC);
CREATE INDEX IF NOT EXISTS idx_aprendizaje_riesgo
    ON aprendizaje_consultas(riesgo_sombra);
