# gimp-imagemagick
Gimp plug-in to access ImageMagick

This is a GIMP plug-in written in Python.  It gives access to the ImageMagick command line using either some built-in
functions or using an ImageMagick command directly.

The plug-in is considerably extended from a more basic example by Michael Munzert.  It was originally hosted on Google
Projects, but apparently is no longer online since Google Projects was shutdown by Google.  I have now created this
repository to house it.

The code is build and tested on Linux and should work under MS Windows, but is (currently) untested on MS Windows.

The code has some lense distortion correcton features which whould be viewed as experimetal.  Note that these features
require SciPy and Numpy to work.  The rest of the plug-in will work without these and it shoud install and run
correctly.

