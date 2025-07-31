#!/usr/bin/env -S sh -c '$(dirname $0)/python/bin/python $0 $@'

import argparse
import os
import sys
import sqlite3
import PIL
import imagehash

#Create an argument parser and parse all arguments.
parser = argparse.ArgumentParser(description = 'Compute perceptual hashes for all images in a '
                                               'given directory and add them to a local database. '
                                               'If run more than once, only add new images '
                                               '(omit existing ones)')
parser.add_argument('images_path',
                    type = str,
                    nargs = 1,
                    help = 'the directory from where to fetch the images')
parser.add_argument('-db', '--database',
                    type = str,
                    default = os.path.join(os.path.dirname(sys.argv[0]), 'image-db.sqlite3'),
                    help = 'the pathname of the sqlite3 database to use (defaults to '
                           'image-db.sqlite3 in the script install directory)')
args = parser.parse_args()

#Create a database connection, then update the schema if needed.
con = sqlite3.connect(args.database)

schema_cursor = con.cursor();

#Uncomment in order to manually delete all perceptual hashes.
# schema_cursor.execute('DROP TABLE images')

#Uncomment in order to manually delete all indexes.
# for i in range(8):
#   schema_cursor.execute('DROP INDEX hash_level_{}'.format(i))

#Create a table with filenames (not paths) and hashes split in individual octets (H0, H1, ... H7)
schema_cursor.execute(
  'CREATE TABLE IF NOT EXISTS images(filename STRING NOT NULL, {})'.format(
    ', '.join('H{} TINYINT'.format(i) for i in range(8))))

#Create indexes for all hash tuples in the form (H0), (H0, H1), (H0, H1, H2), etc.
for i in range(8):
  schema_cursor.execute(
    'CREATE INDEX IF NOT EXISTS hash_level_{} ON images({})'.format(
    i,
    ', '.join('H{}'.format(j) for j in range(i+1))))

#Iterate for every image in the target directory.
for filename in os.listdir(args.images_path[0]):
  #Check whether the file is in the images table.
  query_cursor = con.cursor()
  query_cursor.execute('SELECT 1 FROM images WHERE filename = ? LIMIT 1', (filename,))
  if query_cursor.fetchone() is None:
    #Not in the table. Load it.
    path = os.path.join(args.images_path[0], filename)
    try:
      img = PIL.Image.open(path)
    except PIL.UnidentifiedImageError:
      print('Not an image file: {}'.format(filename))
      continue  #Ignore files that are not images

    #Calculate the hash for every 90 degreee rotation of this image, then structure it as individual
    #bytes in a tuple.
    hashes = set()  #Use a set to reduce the hashes of images with rotational symmetry
    for angle in range(0, 360, 90):
      string_hash = str(imagehash.phash(img.rotate(angle, expand = True)))
      tuple_hash = tuple(int(string_hash[i: i+2], 16) for i in range(0, len(string_hash), 2))
      hashes.update(set((tuple_hash,)))

    #Store every unique hash in the images table.
    insert_cursor = con.cursor()
    for h in hashes:
      insert_cursor.execute(
        'INSERT INTO images(filename,{}) VALUES ({})'.format(
          ','.join('H{}'.format(i) for i in range(8)),
          ','.join(('?') * 9)),
        (filename,) + h)

    con.commit()
