-- Post-use evaluation form, ฉบับที่ 2.0 (19 ก.พ. 2569)
-- One row per submission. The app runs this file at every start-up;
-- every statement is "IF NOT EXISTS", so running it again changes nothing.
--
-- The CHECK constraints repeat the app's validation inside the database,
-- so a bad value can never be stored, even by a manual INSERT.

CREATE TABLE IF NOT EXISTS evaluations (
    id                      BIGSERIAL    PRIMARY KEY,
    submitted_at            TIMESTAMPTZ  NOT NULL DEFAULT now(),
    form_version            TEXT         NOT NULL,

    usage_frequency         TEXT         NOT NULL CHECK (usage_frequency IN (
                                'ไม่ใช้เลย', 'นานๆครั้ง', 'บ่อยแต่ไม่ทุกวัน',
                                'ทุกวัน แต่ไม่ทุกมื้อ', 'ทุกวัน และทุกมื้อ')),

    -- 16 satisfaction items, 1 = น้อยที่สุด ... 5 = มากที่สุด
    -- (sat_switch_likelihood: 1 = ไม่เปลี่ยนแน่นอน ... 5 = เปลี่ยนแน่นอน)
    sat_shape               SMALLINT     NOT NULL CHECK (sat_shape BETWEEN 1 AND 5),
    sat_grip                SMALLINT     NOT NULL CHECK (sat_grip BETWEEN 1 AND 5),
    sat_weight              SMALLINT     NOT NULL CHECK (sat_weight BETWEEN 1 AND 5),
    sat_button              SMALLINT     NOT NULL CHECK (sat_button BETWEEN 1 AND 5),
    sat_light_display       SMALLINT     NOT NULL CHECK (sat_light_display BETWEEN 1 AND 5),
    sat_light_brightness    SMALLINT     NOT NULL CHECK (sat_light_brightness BETWEEN 1 AND 5),
    sat_speed               SMALLINT     NOT NULL CHECK (sat_speed BETWEEN 1 AND 5),
    sat_accuracy            SMALLINT     NOT NULL CHECK (sat_accuracy BETWEEN 1 AND 5),
    sat_cleaning            SMALLINT     NOT NULL CHECK (sat_cleaning BETWEEN 1 AND 5),
    sat_coating_durability  SMALLINT     NOT NULL CHECK (sat_coating_durability BETWEEN 1 AND 5),
    sat_battery_life        SMALLINT     NOT NULL CHECK (sat_battery_life BETWEEN 1 AND 5),
    sat_storage             SMALLINT     NOT NULL CHECK (sat_storage BETWEEN 1 AND 5),
    sat_portability         SMALLINT     NOT NULL CHECK (sat_portability BETWEEN 1 AND 5),
    sat_dipped_food         SMALLINT     NOT NULL CHECK (sat_dipped_food BETWEEN 1 AND 5),
    sat_health_benefit      SMALLINT     NOT NULL CHECK (sat_health_benefit BETWEEN 1 AND 5),
    sat_switch_likelihood   SMALLINT     NOT NULL CHECK (sat_switch_likelihood BETWEEN 1 AND 5),

    calibration_awareness   TEXT         NOT NULL CHECK (calibration_awareness IN (
                                'ไม่ทราบเลย', 'ทราบ แต่ไม่เคยทำ', 'ทราบ และเคยทำแล้ว')),
    -- Only filled when calibration_awareness = 'ทราบ และเคยทำแล้ว' (optional even then)
    calibration_times       INTEGER      CHECK (calibration_times >= 0),

    price_agreement         TEXT         NOT NULL CHECK (price_agreement IN ('เห็นด้วย', 'ไม่เห็นด้วย')),
    suggestions             TEXT         NOT NULL DEFAULT '',
    user_agent              TEXT         NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS evaluations_submitted_at_idx ON evaluations (submitted_at);
