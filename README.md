Scripts for searching similar images using perceptual hashes.
=============================================================

Preparing the python virtual environment.
-----------------------------------------

The scripts provided in this repository make use of the virtual environment feature of the python
language in order to provide isolation from the system libraries. In order to prepare the virtual
environment, run the setup script from the repository directory:

```shell
$ ./setup.sh
```

Adding perceptual hashes to the database.
-----------------------------------------

In order to search for similar images it's needed to add them to the local database first. Run the
update script and provide a directory path with images. Relative and absolute paths are allowed.

```shell
$ ./update-hash-database.py path-to-images
```

Searching for images similar to an specific one.
------------------------------------------------

By passing an image pathname to the search script, similar images can be searched in the local
database.

```shell
$ ./search-similar-images.py path-to-reference-image --hamming-dist N
```

This will give a list of filenames (without path) of those images that match the reference one. In
this case the reference image does not need to be in the database (if it is already, its name will
appear in the results). The hamming distance parameter, which can be abbreviated to `-d`, indicates
how similar the image is allowed to be, with 0 meaning "very similar" and 16 meaning "not very
similar". If omitted, the default hamming distance is 0.

Searching for similar images across the entire database.
--------------------------------------------------------

By omitting the reference image, a full search across the entire database is performed.

```shell
$ ./search-similar-images.py --hamming-dist N
```

This will compare every image in the database against each other and will give a list of similar
image groups. Groups are formed by coalescing similarity chains, meaning that dissimilar images may
appear in the same group, which is an indication that there might be images "in between".

For example:
- Image A is similar to image B.
- Image B is similar to image C.
- Image A is not similar to image C (their hamming distance is too large).
- Images A, B and C appear in the same group anyway, with image B sitting "in between".

Please note that this operation can take very long, specially for larger hamming distances, as more
computational effort is needed in order to discard potential matching candidates.
