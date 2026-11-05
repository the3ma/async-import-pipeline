CREATE TABLE IF NOT EXISTS imports (
  task_id       uuid PRIMARY KEY,
  status        text NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'processing', 'success', 'error')),
  filename      text,
  folder        text NOT NULL,
  error_code    text NOT NULL DEFAULT '',
  message       text NOT NULL DEFAULT '',
  record_ids    uuid[] NOT NULL DEFAULT '{}',
  attempts      int NOT NULL DEFAULT 0,
  expires_at    timestamptz NOT NULL,
  created_at    timestamptz NOT NULL DEFAULT now(),
  modified_at   timestamptz NOT NULL DEFAULT now()
);

-- The sweeper only ever looks at unfinished jobs.
CREATE INDEX IF NOT EXISTS imports_open ON imports (modified_at)
  WHERE status IN ('pending', 'processing');

CREATE TABLE IF NOT EXISTS records (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  sku         text NOT NULL UNIQUE,
  name        text NOT NULL,
  price       numeric(12, 2) NOT NULL CHECK (price >= 0),
  modified_at timestamptz NOT NULL DEFAULT now()
);
