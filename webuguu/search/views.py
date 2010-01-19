# webuguu.search.views - search view for django framework
#
# Copyright 2010, savrus
# Read the COPYING file in the root of the source tree.
#

import psycopg2
from django.http import HttpResponse
from django.shortcuts import render_to_response
import string

db_host = "localhost"
db_user = "postgres"
db_password = ""
db_database = "uguu"

def search(request):
    try:
        query = request.GET['q']
    except:
        return render_to_response('search/index.html')
    try:
        db = psycopg2.connect(
            "host='{h}' user='{u}' " \
            "password='{p}' dbname='{d}'".format(
                h=db_host, u=db_user, p=db_password, d=db_database))
    except:
        return HttpResponse("Unable to connect to the database.")
    cursor = db.cursor()
    cursor.execute("""
        SELECT protocol, hosts.name,
            paths.path, spaths.path, filenames.name, files.size, shares.port
        FROM filenames
        JOIN files ON (filenames.filename_id = files.filename_id)
        LEFT OUTER JOIN paths ON (files.share_id = paths.share_id
            AND files.sharepath_id = paths.sharepath_id)
        LEFT OUTER JOIN paths AS spaths ON (files.share_id = spaths.share_id
            AND files.sharedir_id = spaths.sharepath_id)
        JOIN shares ON (files.share_id = shares.share_id)
        JOIN hosts ON (shares.host_id = hosts.host_id)
        WHERE filenames.name like %(q)s
        ORDER BY files.share_id, files.sharepath_id,
            files.pathfile_id
        """, {'q': "%" + query + "%"})
    if cursor.rowcount == 0:
        return render_to_response('search/noresults.html')
    else:
        return render_to_response('search/results.html',
            {'results': cursor.fetchall()})
