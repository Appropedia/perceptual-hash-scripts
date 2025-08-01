#!/usr/bin/env -S sh -c '$(dirname $0)/python/bin/python $0 $@'

import argparse
import os
import sys
import sqlite3
import PIL
import imagehash
import json

#Perform a recursive depth-first search on all image hashes in the database that are within a
#maximum hamming distance from a given reference hash.
#Parameters:
# - con: Database connection.
# - ref_hash: The hash that is used as a reference point for the search.
# - max_dist: The maximum allowed hamming distance. Images farther than this are excluded.
# - cand_hash: For recursive calls only - The current candidate hash. A partial hash that is within
#              the maximum hamming distance and is currently being analyzed.
# - cand_dist: For recursive calls only - The hamming distance of the current candidate hash.
#Return value: A set with the filenames of the images of which the hash is within the maximum
#              hamming distance.
def search_similar_images(con, ref_hash, max_dist, cand_hash = (), cand_dist = 0):
  #The hash level represents the current depth of the search. It counts the amount of bytes of the
  #current candidate hash.
  hash_level = len(cand_hash)

  #Search for all distinct hahses in the current hash level, using the candidate hash as the fixed
  #portion for all previous levels.
  hash_byte_cursor = con.cursor()
  hash_byte_cursor.execute(
    'SELECT DISTINCT H{} FROM images{}'.format(
      hash_level,
      '' if hash_level == 0 else
      ' WHERE {}'.format(' AND '.join('H{}=?'.format(i) for i in range(hash_level)))),
    cand_hash)
  hash_byte_cursor.row_factory = lambda cur, row: row[0]

  matches = set()
  for hash_byte in hash_byte_cursor:
    #Find all bits that differ from the reference hash at the same level by using an XOR mask, then
    #count the bits that are set and add them to the new candidate distance.
    different_bits = hash_byte ^ ref_hash[hash_level]
    new_cand_dist = cand_dist
    while different_bits > 0:
      different_bits &= different_bits - 1
      new_cand_dist += 1

    if new_cand_dist <= max_dist:
      new_cand_hash = cand_hash + (hash_byte,)

      if hash_level < 7:
        #Maximum hash level not reached - recurse.
        matches.update(search_similar_images(con, ref_hash, max_dist, new_cand_hash, new_cand_dist))
      else:
        #Maximum hash level reached. Search for all images with the new candidate hash and add them
        #to the matches.
        filename_cursor = con.cursor()
        filename_cursor.execute(
          'SELECT filename FROM images where {}'.format(
            ' AND '.join('H{}=?'.format(i) for i in range(8))),
          new_cand_hash)
        filename_cursor.row_factory = lambda cur, row: row[0]
        matches.update(filename_cursor.fetchall())

  return matches

#Recursively merge all sets that share common elements in a given list.
#Parameters:
# - set_list: A list containing the sets to merge. It is modified in place, so the result is
#             returned here as well. This is done in order to save memory on potentially large lists
#             of sets.
def merge_sets(set_list):
  merged_set_list = []  #The resulting merged set list is assembled iteratively
  recurse = False

  while set_list:
    #Iterate over the input set list by popping individual sets.
    s = set_list.pop()
    merge_count = 0

    #Iterate over the current merged set list.
    for m in merged_set_list:
      #If any of the elements of the current set is shared with the current merged set, merge it and
      #increase the merge count.
      if s & m:
        m.update(s)
        merge_count += 1

    #If the current set wasn't merged with any of the previously merged sets, carry it over.
    if merge_count == 0:
      merged_set_list.append(s)

    #If the current set was merged with more than one of the previously merged sets, they will
    #require to be merged again.
    if merge_count > 1:
      recurse = True

  #Having all its elements popped, the input set list is now empty. Populate it with the merged set
  #list now.
  set_list.extend(merged_set_list)
  del merged_set_list

  if recurse:
    merge_sets(set_list)

#Print a simple ascii progress bar. Reprints the bar on the same line if the operation hasn't
#finished. Prints a newline when the operation is finished.
#Parameters:
# - current: An integer representing the amount of operations performed already.
# - total: An integer representing the total amount of operations.
def show_progress(current, total):
  total_width = 70  #This is the proper bar width, not counting surrounding characters
  current_width = total_width * current // total
  print('\r[{}{}] {}%'.format(
      '=' * current_width,
      '-' * (total_width - current_width),
      100 * current // total),
    end='' if current < total else '\n',
    file = sys.stderr)

#Perform a single image search on the database for similar images, then print all matches.
def do_single_search(con, image_file, max_dist, json_output):
  img = PIL.Image.open(image_file)
  string_hash = str(imagehash.phash(img))
  tuple_hash = tuple(int(string_hash[i: i+2], 16) for i in range(0, len(string_hash), 2))

  matches = search_similar_images(con, tuple_hash, max_dist)

  #Format and print the results.
  if json_output:
    print(json.dumps(tuple(matches), indent = 2))
  else:
    if matches:
      print('\n'.join('{}'.format(filename) for filename in matches))
    else:
      print('no matches found')

#Perform a full search on the image database for similar images, then print them in similarity
#groups.
#Parameters:
# - max_dist: The maximum allowed hamming distance. Images are grouped by coalescing chains.
def do_full_search(con, max_dist, json_output):
  #Obtain the amount of distinct images in the table.
  image_total = con.execute('SELECT COUNT(DISTINCT filename) FROM images').fetchone()[0]

  #There can be up to 4 hashes for each image (one per rotation). Get only one of those hashes, as
  #searching for rotations is redundant.
  image_cursor = con.cursor()
  image_cursor.execute(
    'SELECT filename,{0} FROM '
      '(SELECT filename,{0},ROW_NUMBER() OVER (PARTITION BY filename) AS row_num FROM images) '
    'WHERE row_num=1'.format(
      ','.join('H{}'.format(i) for i in range(8))))
  image_cursor.row_factory = lambda cur, row: (row[0], row[1:9])

  #Iterate for every search result.
  image_count = 0
  match_list = []
  for filename, ref_hash in image_cursor:
    show_progress(image_count, image_total)
    image_count += 1

    #Look for similar images to this one. Note that this will always include the reference image, as
    #its hash was taken from the same table.
    matches = search_similar_images(con, ref_hash, max_dist)

    #Check whether the matches contain more than the reference image itself (that is wether the
    #image is similar to any other one). If so add them to the match list.
    if len(matches) > 1:
      match_list.append(matches)

  show_progress(image_count, image_total)   #Finalize progress reporting

  #Merge all match sets (coalesces chains).
  merge_sets(match_list)

  #Format and print the results.
  if json_output:
    print(json.dumps([tuple(s) for s in match_list], indent = 2))
  else:
    if match_list:
      for index, match_set in enumerate(match_list):
        print('Group {}'.format(index))
        print('\n'.join('  {}'.format(filename) for filename in match_set))
    else:
      print('no matches found')

#Create an argument parser and parse all arguments.
parser = argparse.ArgumentParser(description = 'Search for similar images using perceptual hashes')
parser.add_argument('image_file',
                    type = str,
                    nargs = '?',
                    help = 'image to be used as reference - perform a full database search if '
                           'omitted')
parser.add_argument('-d', '--hamming-dist',
                    type = int,
                    default = 0,
                    help = 'measures how different the image s allowed to be (range 0-16, default '
                           'is 0 which means very similar)')
parser.add_argument('-j', '--json',
                    action = 'store_true',
                    help = 'Generate output in JSON format instead of simple text')
parser.add_argument('-db', '--database',
                    type = str,
                    default = os.path.join(os.path.dirname(sys.argv[0]), 'image-db.sqlite3'),
                    help = 'the pathname of the sqlite3 database to use (defaults to '
                           'image-db.sqlite3 in the script install directory)')
args = parser.parse_args()

#Make sure the hamming distance is not too big, otherwise searches will take too long.
if args.hamming_dist > 16:
  print('Hamming distance is too large')
  exit(-1)

#Create a database connection.
con = sqlite3.connect(args.database)

#Do a single image search if an image filename was provided. Do a full search otherwise.
if args.image_file:
  do_single_search(con, args.image_file, args.hamming_dist, args.json)
else:
  do_full_search(con, args.hamming_dist, args.json)
