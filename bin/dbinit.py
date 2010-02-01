#!/usr/bin/python
#
# dbinit.py - initialise uguu database
#
# Copyright 2010, savrus
# Read the COPYING file in the root of the source tree.
#

import psycopg2
import sys
from common import connectdb

def drop(db):
    cursor = db.cursor()
    cursor.execute("""
        DROP TABLE IF EXISTS networks, scantypes, shares, paths,
            filenames, files CASCADE
        """)


def ddl(db):
    cursor = db.cursor()
    cursor.execute("""
        CREATE TABLE networks (
            network varchar(32) PRIMARY KEY
        );
        CREATE TABLE scantypes (
            scantype_id SERIAL PRIMARY KEY,
            scan_command text
        );
        CREATE TABLE shares (
            share_id SERIAL PRIMARY KEY,
            scantype_id integer REFERENCES scantypes ON DELETE RESTRICT,
            network varchar(32) REFERENCES networks ON DELETE CASCADE,
            protocol varchar(8),
            hostname varchar(64),
            port smallint DEFAULT 0,
            state boolean DEFAULT FALSE,
            size bigint,
            last_state_change timestamp,
            last_scan timestamp
        );
        CREATE TABLE paths (
            share_id integer REFERENCES shares ON DELETE CASCADE,
            sharepath_id integer,
            parent_id integer,
            parentfile_id integer,
            path text,
            items integer,
            size bigint,
            tspath tsvector,
            PRIMARY KEY (share_id, sharepath_id)
        );
        CREATE TABLE filenames (
            filename_id BIGSERIAL PRIMARY KEY,
            name text,
            type varchar(16),
            tsname tsvector
        );
        CREATE TABLE files (
            share_id integer,
            sharepath_id integer,
            pathfile_id integer,
            sharedir_id integer,
            size bigint,
            filename_id bigint REFERENCES filenames ON DELETE RESTRICT,
            FOREIGN KEY (share_id, sharepath_id) REFERENCES paths
                ON DELETE CASCADE,
            PRIMARY KEY (share_id, sharepath_id, pathfile_id)
        );
        """)

def ddl_prog(db):
    cursor = db.cursor()
    cursor.execute("""
        CREATE OR REPLACE FUNCTION share_state_change()
            RETURNS trigger AS
            $$BEGIN
                IF NEW.state != OLD.state THEN
                    NEW.last_state_change = 'now';
                END IF;
                RETURN NEW;
            END;$$
            LANGUAGE 'plpgsql' VOLATILE COST 100;
        CREATE TRIGGER share_stage_change_trigger
            BEFORE UPDATE ON shares FOR EACH ROW
            EXECUTE PROCEDURE share_state_change();
	""")

def fill(db):
    cursor = db.cursor()
    cursor.execute("""
        INSERT INTO networks (network)
        VALUES ('localnet');

        INSERT INTO scantypes (scan_command)
        VALUES ('smbscan');

        INSERT INTO shares (scantype_id, network, protocol, hostname)
        VALUES (1, 'localnet', 'smb', '127.0.0.1');
        """)

def textsearch(db):
    cursor = db.cursor()
    cursor.execute("""
        CREATE TEXT SEARCH CONFIGURATION public.uguu
        (COPY = pg_catalog.english);

        ALTER TEXT SEARCH CONFIGURATION uguu
        ALTER MAPPING for asciiword, numword WITH english_stem;
        
        ALTER TEXT SEARCH CONFIGURATION uguu
        ALTER MAPPING for word WITH russian_stem;
        """)

try:
    db = connectdb()
except:
    print "I am unable to connect to the database, exiting."
    sys.exit()

drop(db)
ddl(db)
ddl_prog(db)
fill(db)
db.commit()

