BEGIN;

CREATE TABLE industry_codes (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    changed_at TIMESTAMPTZ,
    source_window TEXT,
    collected_at TIMESTAMPTZ NOT NULL,
    raw_json JSONB NOT NULL DEFAULT '{}'::JSONB
);

CREATE TABLE product_codes (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    changed_at TIMESTAMPTZ,
    source_window TEXT,
    collected_at TIMESTAMPTZ NOT NULL,
    raw_json JSONB NOT NULL DEFAULT '{}'::JSONB
);

CREATE TABLE institution_codes (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    changed_at TIMESTAMPTZ,
    source_window TEXT,
    collected_at TIMESTAMPTZ NOT NULL,
    raw_json JSONB NOT NULL DEFAULT '{}'::JSONB
);

CREATE TABLE companies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    business_registration_number VARCHAR(10) UNIQUE,
    region_code TEXT,
    region_name TEXT,
    company_size TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT companies_name_not_blank CHECK (BTRIM(name) <> ''),
    CONSTRAINT companies_business_number_format CHECK (
        business_registration_number IS NULL
        OR business_registration_number ~ '^[0-9]{10}$'
    ),
    CONSTRAINT companies_size_valid CHECK (
        company_size IN ('MICRO', 'SMALL', 'MEDIUM', 'MID_SIZED', 'LARGE', 'NONE')
    )
);

CREATE TABLE company_industries (
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    industry_code TEXT NOT NULL REFERENCES industry_codes(code),
    verified BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (company_id, industry_code)
);

CREATE TABLE company_staff (
    company_id UUID PRIMARY KEY REFERENCES companies(id) ON DELETE CASCADE,
    total_count INTEGER NOT NULL DEFAULT 0,
    verified BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT company_staff_total_nonnegative CHECK (total_count >= 0)
);

CREATE TABLE company_staff_roles (
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    role_name TEXT NOT NULL,
    headcount INTEGER NOT NULL,
    verified BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (company_id, role_name),
    CONSTRAINT company_staff_roles_name_not_blank CHECK (BTRIM(role_name) <> ''),
    CONSTRAINT company_staff_roles_headcount_nonnegative CHECK (headcount >= 0)
);

CREATE TABLE company_performances (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    client_name TEXT,
    client_institution_code TEXT REFERENCES institution_codes(code),
    amount NUMERIC(18, 0) NOT NULL,
    started_at DATE,
    completed_at DATE NOT NULL,
    description TEXT,
    verified BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT company_performances_name_not_blank CHECK (BTRIM(name) <> ''),
    CONSTRAINT company_performances_amount_nonnegative CHECK (amount >= 0),
    CONSTRAINT company_performances_date_order CHECK (
        started_at IS NULL OR started_at <= completed_at
    )
);

CREATE TABLE company_performance_fields (
    performance_id UUID NOT NULL REFERENCES company_performances(id) ON DELETE CASCADE,
    field_name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (performance_id, field_name),
    CONSTRAINT company_performance_fields_name_not_blank CHECK (BTRIM(field_name) <> '')
);

CREATE TABLE company_certifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    certificate_number TEXT,
    issuer_name TEXT,
    issued_at DATE,
    expires_at DATE,
    verified BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT company_certifications_name_not_blank CHECK (BTRIM(name) <> ''),
    CONSTRAINT company_certifications_date_order CHECK (
        issued_at IS NULL OR expires_at IS NULL OR issued_at <= expires_at
    )
);

CREATE INDEX idx_industry_codes_name ON industry_codes (name);
CREATE INDEX idx_product_codes_name ON product_codes (name);
CREATE INDEX idx_institution_codes_name ON institution_codes (name);
CREATE INDEX idx_company_performances_company_completed
    ON company_performances (company_id, completed_at DESC);
CREATE INDEX idx_company_certifications_company
    ON company_certifications (company_id);

CREATE FUNCTION set_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

CREATE TRIGGER companies_set_updated_at
BEFORE UPDATE ON companies
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER company_staff_set_updated_at
BEFORE UPDATE ON company_staff
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER company_staff_roles_set_updated_at
BEFORE UPDATE ON company_staff_roles
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER company_performances_set_updated_at
BEFORE UPDATE ON company_performances
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER company_certifications_set_updated_at
BEFORE UPDATE ON company_certifications
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMENT ON COLUMN company_industries.verified IS
    'Whether the company marked supporting evidence as held; not third-party verification.';
COMMENT ON COLUMN company_staff.verified IS
    'Whether the company marked supporting evidence as held; not third-party verification.';
COMMENT ON COLUMN company_staff_roles.verified IS
    'Whether the company marked supporting evidence as held; not third-party verification.';
COMMENT ON COLUMN company_performances.verified IS
    'Whether the company marked supporting evidence as held; not third-party verification.';
COMMENT ON COLUMN company_certifications.verified IS
    'Whether the company marked supporting evidence as held; not third-party verification.';

COMMIT;
