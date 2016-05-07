--
-- PostgreSQL database dump
--

SET client_encoding = 'UTF8';

--
-- Name: users; Type: TABLE; Schema: public; Owner: USER; Tablespace: 
--

CREATE TABLE users (
    user_id bigint NOT NULL,
    user_name text,
    options text[],
    hints text,
    wins integer DEFAULT 0,
    losses integer DEFAULT 0,
    messages integer DEFAULT 0,
    last_message timestamp with time zone DEFAULT now()
);

--
-- Name: user_id; Type: CONSTRAINT; Schema: public; Owner: USER; Tablespace: 
--

ALTER TABLE ONLY users
    ADD CONSTRAINT user_id UNIQUE (user_id);

--
-- PostgreSQL database dump complete
--
