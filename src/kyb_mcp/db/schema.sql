-- Idempotent schema for the dossier store. Applied at startup by PostgresDossierRepo.connect().
CREATE TABLE IF NOT EXISTS dossiers (
    id           text PRIMARY KEY,
    siren        char(9) NOT NULL,
    company_name text NOT NULL,
    status       text NOT NULL CHECK (status IN ('open', 'in_review', 'approved', 'rejected', 'archived')),
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS dossiers_status_idx ON dossiers (status);
CREATE INDEX IF NOT EXISTS dossiers_siren_idx ON dossiers (siren);

CREATE TABLE IF NOT EXISTS dossier_notes (
    id         text PRIMARY KEY,
    dossier_id text NOT NULL REFERENCES dossiers (id) ON DELETE CASCADE,
    kind       text NOT NULL DEFAULT 'note' CHECK (kind IN ('note', 'ai_summary', 'system')),
    body       text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS dossier_notes_dossier_idx ON dossier_notes (dossier_id, created_at);
