#!/usr/bin/env python

'''
mm_tool_imagemagick.py

ImageMagick functionality with GIMP

Author:
Michael Munzert (mail mm-log com)
Modified and extended:
Stephen Geary ( sjgcit  gmail com )
JLLC is José Luis Lara Carrascal

Version: $Id: mm_tool_imagemagick.py,v 1.198 2015/11/17 22:59:14 sjg Exp $
2015.11.17 JLLC - Correct typo is temp var name
                - Correct out of date developer email info
2014.02.25 SJG  - Add Colorspace conversion routines
2014.02.22 SJG  - Modify the way scipy and numpy are imported
                        This make sure the rest of the plugin is registered
                        and only the parts that require scipy will not be
                        registered.
2014.02.21 SJG  - Fix an issue with the way popen() works on MS Windows
                        You have to explicitly state the stdin channel must
                        be redirected to PIPE or popen() can fail.
2014.02.20 SJG  - Add checks on getstrokes() return value is None
                - Add lens distorion correction by path using Linear
                        and Quadratic models
                - Add a kludge to command line o try and avoid a problem
                        on some MS Windows system
2014.02.19 SJG  - Added config value for resize filter to retain last value
2014.02.17 SJG  - Added support for mm_tool_imagemagick configuration file in gimp.directory
                - Fixed bug in perspective tool related to use using vertical guides
                - Changed ordering of undo group start and end until after avoidable error returns
                - Changed handling of tempfile creation to avoid runtime errors
                - Fixed bug in use creation of tempimage ( was using layer[0] not tempdrawable ) .
2014.02.16 SJG  - Changes to simply registration code.
                  Addition of experimental lens correction tools using paths.
2014.02.12 SJG  - Change rotation tool to automatically detect whether to use
                        vertical or horizontal as target.
2014.02.09 SJG  - Add a plugin allow any mogrify command to be entered by the user
           SJG  - Add code to request resize filter list from ImageMagick ar runtime
           SJG  - Add support for resize filters with Perspective and Rotate tools
2014.02.08 SJG  - Replace all backslashes in file paths with forward slashes on Windows
2014.02.04 SJG  - Added rotation tool using path
           SJG  - Added color dot product tool
           SJG  - Added color distance tool
2014.02.03 SJG  - Added perspective correction based on path
           SJG  - Changed MS Windows path and added some error handling
           SJG  - Added better undo support
           SJG  - Improved perspective tranformation
2014.02.02 SJG  - Refactored code
           SJG  - Added 'sketch' plugin
           SJG  - Added 'charcoal' plugin
           SJG  - Added Sepia tone plugin
           SJG  - Allow update of plugin window during subprocess execution
           SJG  - Changed menu placement
2014.02.01 SJG  - Added better control of source and destination image and layer
           SJG  - Changed Menu placement and name
           SJG  - Changed function name
2014.01.31 SJG  - Added more filters
2010.02.03 MM   - Added different filters.

modelled after the trace plugin (lloyd konneker, lkk, bootch at nc.rr.com) 

License:

This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 2 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

The GNU Public License is available at
http://www.gnu.org/copyleft/gpl.html

'''

from gimpfu import *
import subprocess
import os
import sys
import time
import gtk
import math
import shutil

try:
    import numpy

    numpy_imported = True

    try:
        import scipy.optimize as scopt

        scipy_imported = True
    except:
        scipy_imported = False
    
except ImportError:
    numpy_imported = False
    scipy_imported = False

#----------------------------------------------------------------------------------

def plugin_maketempfile( image, src ):

    # Copy so the save operations doesn't affect the original
    tempimage = pdb.gimp_image_duplicate( image )
    
    if not tempimage:
        print "mm_tool_imagemagick could not create temporary image file."
        return None, None, None
    
    # Use temp file names from gimp, it reflects the user's choices in gimp.rc
    tempfilename = pdb.gimp_temp_name( "tif" )
    
    if sys.platform.startswith( "win" ):
        # on MS Windows we can use either forward- or back- slashes
        # in file paths.
        # Backslashes can be problematic when dealing with strings
        # so let's replace them just in case.
        tempfilename = tempfilename.replace( "\\", "/" )
    
    if src == 0:  
        # Get the current visible
        tempdrawable = pdb.gimp_layer_new_from_visible( image, tempimage, "visible" ) 
    else:
        # Save in temporary.  Note: empty user entered file name
        tempdrawable = pdb.gimp_image_get_active_drawable( tempimage )

    # !!! Note no run-mode first parameter, and user entered filename is empty string
    pdb.gimp_progress_set_text( "Saving a copy" )
    
    pdb.gimp_file_save( tempimage, tempdrawable, tempfilename, "" )
    
    return tempfilename, tempdrawable, tempimage

#----------------------------------------------------------------------------------

def plugin_saveresult( image, dest, tempfilename, tempimage ):

    # Get image file name
    name = image.filename
    
    if dest == 0 :
        # new image
        try: 
            newimage = pdb.file_tiff_load( tempfilename, "" )

            # Get exif data
            exifdata = image.parasite_find( "exif-data" )

            # Write exif data
            if exifdata != None:  
                newimage.parasite_attach( exifdata )

            # Write name
            if name != None:
                newimage.filename = name

            gimp.Display( newimage )
        except: 
            print "mm_tool_imagemagick could not load tmep file as new image."
        
    elif dest == 1:
        # Replace current layer
        
        pos = pdb.gimp_image_get_item_position( image, image.active_layer )
        
        try:
            newlayer = pdb.gimp_file_load_layer( image, tempfilename )
            
            image.remove_layer( image.active_layer )
            
            image.add_layer( newlayer, pos )
        except:
            print "mm_tool_imagemagick Could not load temp file into existing layer."
        
    elif dest == 2:
        # Add as a new layer in the opened image
        try:
            newlayer = pdb.gimp_file_load_layer( image, tempfilename )
        
            image.add_layer( newlayer,0 )
        except:
            print "mm_tool_imagemagick Could not load temp file into new layer."

    # cleanup
    plugin_tidyup( tempfilename )
    
    # Note the new image is dirty in Gimp and the user will be asked to save before closing.

    gimp.displays_flush()

    gimp.delete( tempimage )   # delete the temporary image
    

#----------------------------------------------------------------------------------

def plugin_tidyup( fname ):

    if os.access( fname, os.F_OK ):
        os.remove( fname )

#----------------------------------------------------------------------------------

def plugin_docommand( function, arg, tempfilename, title ):

    if sys.platform.startswith( "linux" ):
        # Command line for linux
        command = function + " " + arg + " \"" + tempfilename + "\""
    
    elif sys.platform.startswith( "darwin" ):
        # Command line for OSX
        command = function + " " + arg + " \"" + tempfilename + "\""
    
    elif sys.platform.startswith( "win" ):
        # On WIndows we have to find the ImageMagick directory ourselves
        dl = os.listdir( "C:/Program Files" )
        cmdpath = None
        for d in dl:
            # ImageMagick installs to a folder starting with ImageMagick
            # but with version information after that we cannot know
            if d.startswith("ImageMagick"):
                cmdpath = "\"C:/Program Files/" + d + "/" + function + ".exe\""
                break
        command = cmdpath + " " + arg + " \" -quiet " + tempfilename + "\""
    
    else:
        # did not pick up OS from sys.platform
        gimp.message( "OS was not identified by script : " + sys.platform )
        return False
    
    # Invoke mogrify.

    pdb.gimp_progress_set_text( title )
    pdb.gimp_progress_pulse()
    
    # NOTE : Sometimes pythonw.exe fails if you do not PIPE all three
    # of the standard channels, even if your process does not need them.
    # so we must use stdin as well as stdout and stderr
    
    child = subprocess.Popen( command,
                              stderr=subprocess.PIPE,
                              stdout=subprocess.PIPE,
                              stdin=subprocess.PIPE,
                              shell=True
                             )


    # child.communicate()
    
    while child.poll() is None:
        pdb.gimp_progress_pulse()
        time.sleep(0.2)

#    if child.returncode != 0:
    stdoutdata, stderrdata = child.communicate()
    #    gimp.message( "Error return was [ " + stderrdata + "]" )

##__devcode

    print "+----------------------------------------------------------+"
    print stdoutdata
    print "+----------------------------------------------------------+"

##__end_devcode

    return True

#----------------------------------------------------------------------------------

# run a command which returns text but does no image processing

def plugin_silentcommand( function, arg ):

    if sys.platform.startswith( "linux" ):
        # Command line for linux
        command = function + " " + arg
    
    elif sys.platform.startswith( "darwin" ):
        # Command line for OSX
        command = function + " " + arg
    
    elif sys.platform.startswith( "win" ):
        # On WIndows we have to find the ImageMagick directory ourselves
        dl = os.listdir( "C:/Program Files" )
        cmdpath = None
        for d in dl:
            # ImageMagick installs to a folder starting with ImageMagick
            # but with version information after that we cannot know
            if d.startswith("ImageMagick"):
                cmdpath = "\"C:/Program Files/" + d + "/" + function + ".exe\""
                break
        command = cmdpath + " " + arg
    
    else:
        # did not pick up OS from sys.platform
        gimp.message( "OS was not identified by script : " + sys.platform )
        return None
    
    # NOTE : Sometimes pythonw.exe fails if you do not PIPE all three
    # of the standard channels, even if your process does not need them.
    # so we must use stdin as well as stdout and stderr
    
    child = subprocess.Popen( command,
                              stderr=subprocess.PIPE,
                              stdout=subprocess.PIPE,
                              stdin=subprocess.PIPE,
                              shell=True
                             )

    # child.communicate()
    
    stdoutdata, stderrdata = child.communicate()

    return stdoutdata

#----------------------------------------------------------------------------------

def plugin_resize_filters( idx ):

    if not hasattr( plugin_resize_filters, "resize_filters"):
        # initialize
        filters = plugin_silentcommand( "mogrify", "-list filter" )
        if filters != None:
            plugin_resize_filters.resize_filters = filters.split("\n")
        else:
            # fallback in case we could not get the list from mogrify
            plugin_resize_filters.resize_filters = [ "Lanczos",
                "Catrom",
                "Mitchell",
                "Cubic",
                "Point",
                "Box",
                "Triangle",
                "Hermite",
                "Gaussian",
                "Quadratic",
                "Blackman",
                "Hanning",
                "Kaiser",
                "Hamming",
                "Bartlett",
                "Parzen",
                "Welsh",
                "Bohman"
                ]

    if idx == -1:
        return plugin_resize_filters.resize_filters
    else:
        f = plugin_resize_filters.resize_filters[idx]
        plugin_setcfgtag( "default-filter", f )

        return f

#----------------------------------------------------------------------------------

def plugin_color_spaces( idx ):

    if not hasattr( plugin_color_spaces, "colorspaces"):
        # initialize
        cspaces = plugin_silentcommand( "mogrify", "-list colorspace" )
        if cspaces != None:
            plugin_color_spaces.colorspaces = cspaces.split("\n")
        else:
            # fallback in case we could not get the list from mogrify
            plugin_color_spaces.colorspaces = [ "RGB", "HSV", "Lab" ]

    if idx == -1:
        return plugin_color_spaces.colorspaces
    else:
        f = plugin_color_spaces.colorspaces[idx]

        return f

#----------------------------------------------------------------------------------

def getstrokes( image, numpointswanted ):

    vectors = pdb.gimp_image_get_active_vectors(image)
    
    nstrokes, strokes = pdb.gimp_vectors_get_strokes(vectors)
    
    if nstrokes == 0:
        # must be at least one stroke or we have no points
        gimp.message( "No strokes found" )
        return None
    
    stoke_type, n_points, p, closed = pdb.gimp_vectors_stroke_get_points(vectors, strokes[0])
    
    if n_points != 6*numpointswanted:
        # Note that 2 (x,y) ordinate pairs becomes 6 values per ordinate pair
        gimp.message( "Found " + str(n_points/6) + " points, need " + str(numpointswanted) )
        return None
        
    return p
    
#----------------------------------------------------------------------------------

def plugin_resize( image, drawable, size, filtertouse, src, dest ):

    tempfilename, tempdrawable, tempimage = plugin_maketempfile( image, src )
    
    if tempfilename == None:
        return
    
    width  = tempdrawable.width
    height = tempdrawable.height
    
    arg = "-filter " + plugin_resize_filters( filtertouse )
    
    if height > width:
        arg = arg + " -resize x" + str(size) + " "
    else :
        arg = arg + " -resize " + str(size) + " "
    
    plugin_setcfgtag( "default-resize", str(size) )

    pdb.gimp_image_undo_group_start(image)

    if plugin_docommand( "mogrify", arg, tempfilename, "Resizing" ) == True:
        plugin_saveresult( image, dest, tempfilename, tempimage )
        
    plugin_tidyup( tempfilename )

    pdb.gimp_image_undo_group_end(image)

    
#----------------------------------------------------------------------------------

def plugin_sketch( image, drawable, radius, sigma, angle, src, dest ):

    tempfilename, tempdrawable, tempimage = plugin_maketempfile( image, src )
    
    if tempfilename == None:
        return
    
    arg = "-sketch " + str(radius) + "x" + str(sigma) + "+" + str(angle)

    pdb.gimp_image_undo_group_start(image)

    if plugin_docommand( "mogrify", arg, tempfilename, "Sketching" ) == True:
        plugin_saveresult( image, dest, tempfilename, tempimage )
        
    plugin_tidyup( tempfilename )

    pdb.gimp_image_undo_group_end(image)


#----------------------------------------------------------------------------------

def plugin_charcoal( image, drawable, thickness, src, dest ):

    tempfilename, tempdrawable, tempimage = plugin_maketempfile( image, src )
    
    if tempfilename == None:
        return
    
    arg = "-charcoal " + str(thickness)

    pdb.gimp_image_undo_group_start(image)

    if plugin_docommand( "mogrify", arg, tempfilename, "Charcoal rendering" ) == True:
        plugin_saveresult( image, dest, tempfilename, tempimage )
        
    plugin_tidyup( tempfilename )

    pdb.gimp_image_undo_group_end(image)


#----------------------------------------------------------------------------------

def plugin_sepia( image, drawable, threshold, src, dest ):

    tempfilename, tempdrawable, tempimage = plugin_maketempfile( image, src )
    
    if tempfilename == None:
        return
    
    arg = "-sepia-tone " + str(threshold) + "%"

    pdb.gimp_image_undo_group_start(image)

    if plugin_docommand( "mogrify", arg, tempfilename, "Sepia tone rendering" ) == True:
        plugin_saveresult( image, dest, tempfilename, tempimage )
        
    plugin_tidyup( tempfilename )

    pdb.gimp_image_undo_group_end(image)


#----------------------------------------------------------------------------------

def plugin_perspective( image, drawable, force, filtertouse, src, dest ):

    # get points for transform from image
    
    p = getstrokes( image, 4 )
    
    if p == None:
        return
    
    # if force flag is True then we map the points to the top and bottom of
    # the time by projecting lines from the points we have.  This will produce
    # a perspective correction suitable for focing building verticals to be
    # vertical in the final image ( assuming you choose points on the
    # correct lines in the image ).
    
    q = []
    
    if force == True:
        # map the points to the top and bottom of the image
        
        w = drawable.width
        h = drawable.height
        
        # it's possible the lines could be vertical
        # which will error when we divide by zero
        
        if p[6] == p[0]:
            q.append( p[0] )
            q.append( 0 )
            q.append( p[0] )
            q.append( h-1 )
        else:
            a = ( p[7] - p[1] ) / ( p[6] - p[0] )
            b = p[7] - ( a * p[6] )
            
            q.append( -b/a )
            q.append( 0 )
            q.append( ( h-1-b ) / a )
            q.append( h-1 )
            
        if p[18] == p[12]:
            q.append( p[18] )
            q.append( 0 )
            q.append( p[18] )
            q.append( h-1 )
        else:
            a = ( p[19] - p[13] ) / ( p[18] - p[12] )
            b = p[19] - ( a * p[18] )
            
            # note the code that follows expects the order to anti-clockwise
            # so these are added in a different order
            q.append( ( h-1-b ) / a )
            q.append( h-1 )
            q.append( -b/a )
            q.append( 0 )
        
    else:
        # just use the points we're given
        q.append( p[0] )
        q.append( p[1] )
        q.append( p[6] )
        q.append( p[7] )
        q.append( p[12] )
        q.append( p[13] )
        q.append( p[18] )
        q.append( p[19] )
    
    # need to work out the box to map to
    # we do this by using the middle two x and y ordinates of the
    # given points.  We map to this.
    
    # routine assume points were entered from top-left quadrant anti-clockwise
    
    xa = sorted( [ q[0], q[2], q[4], q[6] ] )
    ya = sorted( [ q[1], q[3], q[5], q[7] ] )
    
    # do the transformation

    tempfilename, tempdrawable, tempimage = plugin_maketempfile( image, src )
    
    if tempfilename == None:
        return
    
    arg = "-matte -virtual-pixel transparent -filter " + plugin_resize_filters( filtertouse ) + " -distort Perspective \""
    arg = arg + str(q[0]) + "," + str(q[1]) + " " + str(xa[1]) + "," + str(ya[1]) + " "
    arg = arg + str(q[2]) + "," + str(q[3]) + " " + str(xa[1]) + "," + str(ya[2]) + " "
    arg = arg + str(q[4]) + "," + str(q[5]) + " " + str(xa[2]) + "," + str(ya[2]) + " "
    arg = arg + str(q[6]) + "," + str(q[7]) + " " + str(xa[2]) + "," + str(ya[1]) + " "
    arg = arg + "\""

    pdb.gimp_image_undo_group_start(image)

    if plugin_docommand( "mogrify", arg, tempfilename, "Perspective Transform" ) == True:
        plugin_saveresult( image, dest, tempfilename, tempimage )
    
    plugin_tidyup( tempfilename )

    pdb.gimp_image_undo_group_end(image)

#----------------------------------------------------------------------------------

def plugin_rotate( image, drawable, filtertouse , src, dest ):

    # get points for transform from image
    
    p = getstrokes(image,2)
    
    if p == None:
        return
    
    # calculate angle

    # note that y ordinates are opposite from what you expect
    # in maths, as the top is zero and the bottom is positive
    
    y7 = image.height - 1 - p[7]
    y1 = image.height - 1 - p[1]
    
    if p[6] > p[0]:
        angle0 = math.atan2( y7-y1, p[6]-p[0] )
    else:
        angle0 = math.atan2( y1-y7, p[0]-p[6] )
    
    angle0 = 180.0 * angle0 / math.pi
    
    if angle0 > 0 :
        if angle0 > 45:
            angle = angle0 - 90
        else:
            angle = angle0
    else:
        absangle = math.fabs( angle0 )
    
        if absangle > 45:
            angle = 90 - absangle
        else:
            angle = angle0
    
    # do the transformation

    tempfilename, tempdrawable, tempimage = plugin_maketempfile( image, src )
    
    if tempfilename == None:
        return
    
    arg = "-matte -virtual-pixel transparent -filter " + plugin_resize_filters( filtertouse ) + " +distort SRT \"" + str(angle) + "\" "

    pdb.gimp_image_undo_group_start(image)

    if plugin_docommand( "mogrify", arg, tempfilename, "Rotation" ) == True:
        plugin_saveresult( image, dest, tempfilename, tempimage )
        
    plugin_tidyup( tempfilename )

    pdb.gimp_image_undo_group_end(image)


#----------------------------------------------------------------------------------

##__devcode

def plugin_lenscorrection( image, drawable, filtertouse , src, dest ):

    # get points for transform from image
    
    p = getstrokes(image,5)
    
    if p == None:
        return
    
    # Note that radi are normalized (!)
    
    cx = image.width / 2.0
    cy = image.height / 2.0
    
    norm = cx
    if cy < norm:
        norm = cy
    
    g = ( cx, cy, norm )
    
    R0, s0, c0 = lc_rsc( p, 0, g )
    R1, s1, c1 = lc_rsc( p, 1, g )
    R2, s2, c2 = lc_rsc( p, 2, g )
    R3, s3, c3 = lc_rsc( p, 3, g )
    R4, s4, c4 = lc_rsc( p, 4, g )
    
    print R0, R1, R2, R3, R4
    
    # solve the equation
    #
    # We wish to obtain values for the tansform R = r*( A*r*r*r + B*r*r + C*r*r + D )
    #
    # From logical considerations we get :
    #
    #   B = F*F + E*E - 2 - 2*A
    #   C = 3 + A - F*F - 2*E*E
    #   D = E*E
    #
    # And we fit to that equation
    
    # initial estimate for line we map to
    
    p0 = ( R4*s4 - R0*s0 ) / ( R4*c4 - R0*c0 )
    q0 = R0*s0 - p0*R0*c0
    
    # Note the guess values refer to A,E,F,p,q in that order
    #
    guess = [ 0, 1, 1, p0, q0 ]
    
    # print guess
    
    t = [ R0,s0,c0, R1,s1,c1, R2,s2,c2, R3,s3,c3, R4,s4,c4 ]
    
    # V, covx, info, ier, msg = scopt.leastsq( lc_fn2, guess, t, full_output=True )
    V, info, ier, msg = scopt.fsolve( lc_fn2, guess, t, full_output=True )
    
    D = V[1]*V[1]
    A = V[0]
    B = V[2]*V[2] + D - 2 - 2*A
    C = 1 - A - B - D
    
    print "co-effs = ", A, B, C, D
    
    print info['fvec']
    print info['nfev']
    
    # C now contains the values we need for the ImageMagick barrel distortion correction
    
    # do the transformation

    tempfilename, tempdrawable, tempimage = plugin_maketempfile( image, src )
    
    if tempfilename == None:
        return
    
    arg = "-matte -virtual-pixel transparent -filter " + plugin_resize_filters( filtertouse ) + " -distort Barrel"
    arg = arg + " \""+ str(A) + " " + str(B) + " " + str(C) + " " + str(D) + "\" "

    pdb.gimp_image_undo_group_start(image)

    if plugin_docommand( "mogrify", arg, tempfilename, "Barrel" ) == True:
        plugin_saveresult( image, dest, tempfilename, tempimage )
        
    plugin_tidyup( tempfilename )

    pdb.gimp_image_undo_group_end(image)
    
    print msg

#--------------------------

def lc_fn( V, RSC ):
    
    ( A, G1, H1, p, q ) = V
    ( R0,s0,c0, R1,s1,c1, R2,s2,c2, R3,s3,c3, R4,s4,c4 ) = RSC
    
    B = G1*G1-2-2*A
    
    C = 3-A-H1*H1
    
    eq0 = A*( (q/(s0-p*c0))**4 ) + B*( (q/(s0-p*c0))**3 ) + C*( (q/(s0-p*c0))**2 ) + ( 1-(A+B+C) )*q/(s0-p*c0) - R0
    eq1 = A*( (q/(s1-p*c1))**4 ) + B*( (q/(s1-p*c1))**3 ) + C*( (q/(s1-p*c1))**2 ) + ( 1-(A+B+C) )*q/(s1-p*c1) - R1
    eq2 = A*( (q/(s2-p*c2))**4 ) + B*( (q/(s2-p*c2))**3 ) + C*( (q/(s2-p*c2))**2 ) + ( 1-(A+B+C) )*q/(s2-p*c2) - R2
    eq3 = A*( (q/(s3-p*c3))**4 ) + B*( (q/(s3-p*c3))**3 ) + C*( (q/(s3-p*c3))**2 ) + ( 1-(A+B+C) )*q/(s3-p*c3) - R3
    eq4 = A*( (q/(s4-p*c4))**4 ) + B*( (q/(s4-p*c4))**3 ) + C*( (q/(s4-p*c4))**2 ) + ( 1-(A+B+C) )*q/(s4-p*c4) - R4
    '''
    eq0 = A*(q**4) + B*(q**3)*(s0-p*c0) + C*(q**2)*((s0-p*c0)**2) + (1-(A+B+C))*q*((s0-p*c0)**3) - R0*((s0-p*c0)**4)
    eq1 = A*(q**4) + B*(q**3)*(s1-p*c1) + C*(q**2)*((s1-p*c1)**2) + (1-(A+B+C))*q*((s1-p*c1)**3) - R1*((s1-p*c1)**4)
    eq2 = A*(q**4) + B*(q**3)*(s2-p*c2) + C*(q**2)*((s2-p*c2)**2) + (1-(A+B+C))*q*((s2-p*c2)**3) - R2*((s2-p*c2)**4)
    eq3 = A*(q**4) + B*(q**3)*(s3-p*c3) + C*(q**2)*((s3-p*c3)**2) + (1-(A+B+C))*q*((s3-p*c3)**3) - R3*((s3-p*c3)**4)
    eq4 = A*(q**4) + B*(q**3)*(s4-p*c4) + C*(q**2)*((s4-p*c4)**2) + (1-(A+B+C))*q*((s4-p*c4)**3) - R4*((s4-p*c4)**4)
    '''

    return [ eq0, eq1, eq2, eq3, eq4 ]


#--------------------------

def lc_fn2( V, RSC ):
    
    ( A, E, F, p, q ) = V
    ( R0,s0,c0, R1,s1,c1, R2,s2,c2, R3,s3,c3, R4,s4,c4 ) = RSC
    
    D = E*E
    B = F*F + D - 2 - 2*A
    C = 1 - A - B - D
    
    r = q/(s0-p*c0)
    eq0 = A*( r**4 ) + B*( r**3 ) + C*( r**2 ) + D*r - R0
    r = q/(s1-p*c1)
    eq1 = A*( r**4 ) + B*( r**3 ) + C*( r**2 ) + D*r - R1
    r = q/(s2-p*c2)
    eq2 = A*( r**4 ) + B*( r**3 ) + C*( r**2 ) + D*r - R2
    r = q/(s3-p*c3)
    eq3 = A*( r**4 ) + B*( r**3 ) + C*( r**2 ) + D*r - R3
    r = q/(s4-p*c4)
    eq4 = A*( r**4 ) + B*( r**3 ) + C*( r**2 ) + D*r - R4

    return [ eq0, eq1, eq2, eq3, eq4 ]

##__end_devcode

#--------------------------

def plugin_lc_b( image, drawable, filtertouse , src, dest ):

    '''
    Try to correct lens distortion my matching three points
    on a curve to R = r*( (1-E+E)*r*r + E*E )
    '''

    # get points for transform from image
    
    p = getstrokes(image,3)
    
    if p == None:
        return
    
    # Note that radi are normalized (!)
    
    cx = image.width / 2.0
    cy = image.height / 2.0
    
    norm = cx
    if cy < norm:
        norm = cy
    
    g = ( cx, cy, norm )
    
    R0, s0, c0 = lc_rsc( p, 0, g )
    R1, s1, c1 = lc_rsc( p, 1, g )
    R2, s2, c2 = lc_rsc( p, 2, g )
    
    # solve the equation
    
    # initial estimate for solution
    
    p0 = ( R2*s2 - R0*s0 ) / ( R2*c2 - R0*c0 )
    q0 = R0*s0 - p0*R0*c0
    
    guess = [ 0.0 ,p0, q0 ]
    
    t = [ R0,s0,c0, R1,s1,c1, R2,s2,c2 ]
    
    V, info, ier, msg = scopt.fsolve( lc_fn_b, guess, t, full_output=True )
    
    D = V[0]*V[0]
    B = 1.0 - D
    
    # C now contains the values we need for the ImageMagick barrel distortion correction
    
    # do the transformation

    tempfilename, tempdrawable, tempimage = plugin_maketempfile( image, src )
    
    if tempfilename == None:
        return
    
    arg = "-matte -virtual-pixel transparent -filter " + plugin_resize_filters( filtertouse ) + " -distort Barrel"
    arg = arg + " \"0.0 " + str(B) + " 0.0 " + str(D) + "\" "

    pdb.gimp_image_undo_group_start(image)

    if plugin_docommand( "mogrify", arg, tempfilename, "Barrel" ) == True:
        plugin_saveresult( image, dest, tempfilename, tempimage )
        
    plugin_tidyup( tempfilename )

    pdb.gimp_image_undo_group_end(image)
    
#--------------------------

def lc_fn_b( V, RSC ):
    
    ( E, p, q ) = V
    ( R0,s0,c0, R1,s1,c1, R2,s2,c2 ) = RSC
    
    D = E*E
    
    # fitting R = r*( (1-E*E)*r*r + E*E )
    
    r = q/(s0-p*c0)
    eq0 = ( (1-D)*r*r + D )*r - R0
    r = q/(s1-p*c1)
    eq1 = ( (1-D)*r*r + D )*r - R1
    r = q/(s2-p*c2)
    eq2 = ( (1-D)*r*r + D )*r - R2

    return [ eq0, eq1, eq2 ]


#--------------------------

def plugin_lc_c( image, drawable, filtertouse , src, dest ):

    '''
    Try to correct lens distorion by mapping three points
    on a curve to a line.
    Use the model :  R = r*( C*r + 1 - C )
    '''

    # get points for transform from image
    
    p = getstrokes(image,3)
    
    if p == None:
        return
    
    # Note that radi are normalized (!)
    
    cx = image.width / 2.0
    cy = image.height / 2.0
    
    norm = cx
    if cy < norm:
        norm = cy
    
    g = ( cx, cy, norm )
    
    R0, s0, c0 = lc_rsc( p, 0, g )
    R1, s1, c1 = lc_rsc( p, 1, g )
    R2, s2, c2 = lc_rsc( p, 2, g )
    
    # solve the equation
    
    # initial estimate for solution
    
    p0 = ( R2*s2 - R0*s0 ) / ( R2*c2 - R0*c0 )
    q0 = R0*s0 - p0*R0*c0
    
    guess = [ 0.0 ,p0, q0 ]
    
    t = [ R0,s0,c0, R1,s1,c1, R2,s2,c2 ]
    
    C, info, ier, msg = scopt.fsolve( lc_fn_c, guess, t, full_output=True )
    
    D = 1.0 - C[0]
        
    # C now contains the values we need for the ImageMagick barrel distortion correction
    
    # do the transformation

    tempfilename, tempdrawable, tempimage = plugin_maketempfile( image, src )
    
    if tempfilename == None:
        return
    
    arg = "-matte -virtual-pixel transparent -filter " + plugin_resize_filters( filtertouse ) + " -distort Barrel"
    arg = arg + " \"0.0 0.0 " + str(C[0]) + " " + str(D) + "\" "

    pdb.gimp_image_undo_group_start(image)

    if plugin_docommand( "mogrify", arg, tempfilename, "Barrel" ) == True:
        plugin_saveresult( image, dest, tempfilename, tempimage )
        
    plugin_tidyup( tempfilename )

    pdb.gimp_image_undo_group_end(image)
    
#--------------------------

def lc_fn_c( V, RSC ):
    
    ( C, p, q ) = V
    ( R0,s0,c0, R1,s1,c1, R2,s2,c2 ) = RSC
    
    eq0 = C*(q**2) + (1-C)*q*(s0-p*c0) - R0*((s0-p*c0)**2)
    eq1 = C*(q**2) + (1-C)*q*(s1-p*c1) - R1*((s1-p*c1)**2)
    eq2 = C*(q**2) + (1-C)*q*(s2-p*c2) - R2*((s2-p*c2)**2)

    return [ eq0, eq1, eq2 ]


#--------------------------

def lc_rsc( p, k, g ):

    x = p[6*k] - g[0]
    y = p[(6*k)+1] - g[1]
    R = math.sqrt( x*x + y*y )
    s = y / R
    c = x / R
    R = R / g[2]
    
    return ( R, s, c )

#-----------------------------------

##__devcode

def plugin_lenscorrection_inverse( image, drawable, filtertouse , src, dest ):

    # get points for transform from image
    
    p = getstrokes(image,5)
    
    if p == None:
        return
    
    # Note that radi are normalized (!)
    
    cx = image.width / 2.0
    cy = image.height / 2.0
    
    norm = cx
    if cy < norm:
        norm = cy
    
    g = ( cx, cy, norm )
    
    R0, s0, c0 = lc_rsc( p, 0, g )
    R1, s1, c1 = lc_rsc( p, 1, g )
    R2, s2, c2 = lc_rsc( p, 2, g )
    R3, s3, c3 = lc_rsc( p, 3, g )
    R4, s4, c4 = lc_rsc( p, 4, g )
    
    print R0, R1, R2, R3, R4
    
    # solve the equation
    #
    # We wish to obtain values for the transform R = r/( A*r*r*r + B*r*r + C*r*r + D )
    #
    # From logical considerations we get :
    #
    #   B = E*E - F*F - 2*A
    #   C = 1 + A + F*F - 2*E*E
    #   D = E*E
    #
    # And we fit to that equation
    
    # initial estimate for line we map to
    
    p0 = ( R4*s4 - R0*s0 ) / ( R4*c4 - R0*c0 )
    q0 = R0*s0 - p0*R0*c0
    
    # Note the guess values refer to A,E,F,p,q in that order
    #
    guess = [ 0, 1, 1, p0, q0 ]
    
    # print guess
    
    t = [ R0,s0,c0, R1,s1,c1, R2,s2,c2, R3,s3,c3, R4,s4,c4 ]
    
    # V, covx, info, ier, msg = scopt.leastsq( lc_fninv, guess, t, full_output=True )
    V, info, ier, msg = scopt.fsolve( lc_fninv, guess, t, full_output=True )
    
    D = V[1]*V[1]
    A = V[0]
    B = D - V[2]*V[2] - 2*A
    C = 1 - A - B - D
    
    print "co-effs = ", A, B, C, D
    
    print info['fvec']
    print info['nfev']
    
    # C now contains the values we need for the ImageMagick barrel distortion correction
    
    # do the transformation

    tempfilename, tempdrawable, tempimage = plugin_maketempfile( image, src )
    
    if tempfilename == None:
        return
    
    arg = "-matte -virtual-pixel transparent -filter " + plugin_resize_filters( filtertouse ) + " -distort BarrelInverse"
    arg = arg + " \""+ str(A) + " " + str(B) + " " + str(C) + " " + str(D) + "\" "

    pdb.gimp_image_undo_group_start(image)

    if plugin_docommand( "mogrify", arg, tempfilename, "Barrel" ) == True:
        plugin_saveresult( image, dest, tempfilename, tempimage )
        
    plugin_tidyup( tempfilename )

    pdb.gimp_image_undo_group_end(image)
    
    print msg

#--------------------------

def lc_fninv( V, RSC ):
    
    ( A, E, F, p, q ) = V
    ( R0,s0,c0, R1,s1,c1, R2,s2,c2, R3,s3,c3, R4,s4,c4 ) = RSC
    
    D = E*E
    B = D - F*F - 2*A
    C = 1 - A - B - D
    
    r = q/(s0-p*c0)
    eq0 = ( r/( A*( r**3 ) + B*( r**2 ) + C*r + D ) ) - R0
    r = q/(s1-p*c1)
    eq1 = ( r/( A*( r**3 ) + B*( r**2 ) + C*r + D ) ) - R1
    r = q/(s2-p*c2)
    eq2 = ( r/( A*( r**3 ) + B*( r**2 ) + C*r + D ) ) - R2
    r = q/(s3-p*c3)
    eq3 = ( r/( A*( r**3 ) + B*( r**2 ) + C*r + D ) ) - R3
    r = q/(s4-p*c4)
    eq4 = ( r/( A*( r**3 ) + B*( r**2 ) + C*r + D ) ) - R4

    return [ eq0, eq1, eq2, eq3, eq4 ]

#--------------------------

##__end_devcode
    
#----------------------------------------------------------------------------------

def plugin_colorspaceconversion( image, drawable, spaceto, src, dest ):

    tempfilename, tempdrawable, tempimage = plugin_maketempfile( image, src )
    
    if tempfilename == None:
        return
    
    arg = "-colorspace " + plugin_color_spaces(spaceto) + " -set colorspace RGB"
    
    print "Color space = ", plugin_color_spaces(spaceto) 
    
    pdb.gimp_image_undo_group_start(image)
    
    if plugin_docommand( "mogrify", arg, tempfilename, "Colorspace Conversion" ) == True:
        plugin_saveresult( image, dest, tempfilename, tempimage )
    
    plugin_tidyup( tempfilename )

    pdb.gimp_image_undo_group_end(image)


#----------------------------------------------------------------------------------

def plugin_colordotproduct( image, drawable, src, dest ):

    # get the current foreground color
    
    fg = gimp.get_foreground()
    
    # use the -fx command to process the image
    
    arg = "-fx \"(sqrt( u.r*" + str(fg[0]) + " + u.g*" + str(fg[1]) + "+ u.b*" + str(fg[2]) + " ))/15.97\" "
    
    tempfilename, tempdrawable, tempimage = plugin_maketempfile( image, src )
    
    if tempfilename == None:
        return
    
    pdb.gimp_image_undo_group_start(image)

    if plugin_docommand( "mogrify", arg, tempfilename, "Color Dot Product" ) == True:
        plugin_saveresult( image, dest, tempfilename, tempimage )
        
    plugin_tidyup( tempfilename )

    pdb.gimp_image_undo_group_end(image)


#----------------------------------------------------------------------------------

def plugin_colordistance( image, drawable, src, dest ):

    # get the current foreground color
    
    fg = gimp.get_foreground()
    
    r = float(fg[0])/255.0
    g = float(fg[1])/255.0
    b = float(fg[2])/255.0
    
    # use the -fx command to process the image
    
    arg = "-fx \"(sqrt( ( u.r-" + str(r) + ")^2 + ( u.g-" + str(g) + ")^2 + ( u.b-" + str(b) + ")^2 ))\" "
    
    tempfilename, tempdrawable, tempimage = plugin_maketempfile( image, src )
    
    if tempfilename == None:
        return
    
    pdb.gimp_image_undo_group_start(image)

    if plugin_docommand( "mogrify", arg, tempfilename, "Color Distance" ) == True:
        plugin_saveresult( image, dest, tempfilename, tempimage )
        
    plugin_tidyup( tempfilename )

    pdb.gimp_image_undo_group_end(image)


#----------------------------------------------------------------------------------

def plugin_colordistance_lab( image, drawable, src, dest ):

    tempfilename, tempdrawable, tempimage = plugin_maketempfile( image, src )
    
    if tempfilename == None:
        return
    
    # get the current foreground color
    
    fg = gimp.get_foreground()
    
    # create a new image composed of the foreground color only
    
    bgfilename = pdb.gimp_temp_name( "tif" )
    
    gimp.message( bgfilename )
    
    shutil.copy( tempfilename, bgfilename )
    
    arg = "-fill \"rgb(" + str(fg[0]) + "," + str(fg[1]) + "," + str(fg[2]) + ")\" "
    
    plugin_docommand( "mogrify", arg, bgfilename, "Color Distance LAB creation" )
    
    # use the -fx command to process the image
    
    arg = tempfilename + " " + bgfilename
    arg = arg + " -compose difference "
    
    pdb.gimp_image_undo_group_start(image)

    if plugin_docommand( "convert", arg, tempfilename, "Color Distance LAB" ) == True:
        plugin_saveresult( image, dest, tempfilename, tempimage )
        
    plugin_tidyup( tempfilename )
    
    plugin_tidyup( bgfilename )

    pdb.gimp_image_undo_group_end(image)


#----------------------------------------------------------------------------------

def plugin_usercommand( image, drawable, src, dest, arg ):

    # text may be entered with newlines, so we need to replace them with spaces
    arg = arg.replace( "\n", " " )

    tempfilename, tempdrawable, tempimage = plugin_maketempfile( image, src )
    
    if tempfilename == None:
        return
    
    pdb.gimp_image_undo_group_start(image)

    if plugin_docommand( "mogrify", arg, tempfilename, "User Command" ) == True:
        plugin_saveresult( image, dest, tempfilename, tempimage )
        
    plugin_tidyup( tempfilename )

    pdb.gimp_image_undo_group_end(image)

#----------------------------------------------------------------------------------

def plugin_resource_limits( image, drawable ):

    im_limits = plugin_silentcommand( "mogrify", "-list resource" )
    
    gimp.message( "Mogrify limits :\n\n" + im_limits )

#----------------------------------------------------------------------------------

'''
We use a very simple configurationfile format.
The keys, value pairs are on differnt lines, so
we can easily find a value by locating it's key
and then using the following line as a value.
'''

def plugin_getconfig():

    fname = os.path.join( gimp.directory, "mm_tool_imagemagick.cfg" )
    
    if not os.path.exists( fname ):
        return None
    
    f = open( fname, "r" )
    # this is fast and simple for small files
    # it's not suitable for files that are very large
    # compared to memory, but that's not an issue here.
    cfg = f.read().splitlines()
    f.close()
    
    # it is tempting to remove empty lines and comments but as long
    # as they are not used as keys there is not reason to worry about
    # them.  Keeping them intact lets us write them out later.
    
    return cfg
    
#----------------------------------------------------------------------------------

# Very unhelpfully index() raises an error when something is
# not in a list.  As I don't want code peppered by try..except
# clauses I use this function to instead return a -1 when
# a tag is not in a list ( which is less drastic ).

def plugin_indexof( tag, cfg ):

    try:
        pos = cfg.index(tag)
    except ValueError:
        pos = -1
    
    return pos

#----------------------------------------------------------------------------------

def plugin_getcfgtag( tag ):

    cfg = plugin_getconfig()
    
    if cfg == None:
        return None

    pos = plugin_indexof(tag, cfg)
    
    if pos < 0:
        return None
    else:
        return cfg[pos+1]

#----------------------------------------------------------------------------------

def plugin_setcfgtag( tag, val ):

    cfg = plugin_getconfig()
    
    if cfg == None:
        cfg = [ tag, val ]
    else:
        pos = plugin_indexof(tag, cfg)
        
        if pos < 0:
            cfg.append( tag )
            cfg.append( val )
        else:
            cfg[pos+1] = val

    f = open( os.path.join( gimp.directory, "mm_tool_imagemagick.cfg" ), "w+" )
    
    for g in cfg:
        f.write( g + "\n" )
    
    f.close()
    

#----------------------------------------------------------------------------------


# get default settings

sz = plugin_getcfgtag( "default-resize" )
if sz != None:
    resize_default = int( sz )
else:
    resize_default = 800

filtername = plugin_getcfgtag( "default-filter" )

allfilters = plugin_resize_filters(-1)

filter_idx = 0

if filtername != None:
    filter_idx = plugin_indexof( filtername, allfilters )

# vars for common parameters in registration code

menubase = "<Image>/Filters/MM-Filters/IM "

stdopt_filter = ( PF_OPTION, "filtertouse", "Filter:", filter_idx, allfilters )

stdopt_src = ( PF_RADIO, "src", "Source:", 0, ( ("Visible layers", 0), ("Current layer only",1) ) )

stdopt_dest = ( PF_RADIO, "dest", "Destination:", 0, ( ("New image", 0), ("Current layer",1), ("New layer",2) ) )


register(
                "python_fu_mm_im_resize",
                "Create a new resized image by using ImageMagick and any of it's supported filters.",
                "Create a new resized image by using ImageMagick and any of it's supported filters.",
                "Michael Munzert (mail mm-log com)",
                "Copyright 2010 Michael Munzert",
                "2010",
                menubase + "Resize",
                "*", # image types
                [
                    ( PF_INT, "size", "Longer edge:", resize_default ),
                    stdopt_filter,
                    stdopt_src,
                    stdopt_dest
                ],
                [],
                plugin_resize,
                )

register(
                "python_fu_mm_im_sketch",
                "Process image using ImageMagick sketch to similuate pencil drawing.",
                "Process image using ImageMagick sketch to similuate pencil drawing.",
                "Stephen Geary, ( sg euroapps com )",
                "(c) 2014, Stephen Geary",
                "2014",
                menubase + "Sketch",
                "*",
                [
                    ( PF_FLOAT , "radius", "Radius :", 5.0 ),
                    ( PF_FLOAT , "sigma",  "Sigma  :", 1.0 ),
                    ( PF_SLIDER, "angle",  "Angle  :", 45, [ 0, 360, 5 ] ),
                    stdopt_src,
                    stdopt_dest
                ],
                [],
                plugin_sketch,
                )

register(
                "python_fu_mm_im_charcoal",
                "Process image using ImageMagick sketch to similuate charcoal drawing.",
                "Process image using ImageMagick sketch to similuate charcoal drawing.",
                "Stephen Geary, ( sg euroapps com )",
                "(c) 2014, Stephen Geary",
                "2014",
                menubase + "Charcoal",
                "*",
                [
                    ( PF_FLOAT, "thickness", "Line thickness :", 5.0 ),
                    stdopt_src,
                    stdopt_dest
                ],
                [],
                plugin_charcoal,
                )

register(
                "python_fu_mm_im_sepia",
                "Process image using ImageMagick sepia-tone.",
                "Process image using ImageMagick sepia-tone.",
                "Stephen Geary, ( sg euroapps com )",
                "(c) 2014, Stephen Geary",
                "2014",
                menubase + "Sepia Tone",
                "*",
                [
                    ( PF_SLIDER, "threshold", "Threshold :", 80, [ 0, 100, 5 ] ),
                    stdopt_src,
                    stdopt_dest
                ],
                [],
                plugin_sepia,
                )

register(
                "python_fu_mm_im_perspective",
                "Perspective transform using path from image and ImageMagick.",
                "Perspective transform using path from image and ImageMagick.  Select four points forming a rough 'U' shape with the verrticals along two converging lines you want to be made perfectly vertical.",
                "Stephen Geary, ( sg euroapps com )",
                "(c) 2014, Stephen Geary",
                "2014",
                menubase + "Perspective from path",
                "*",
                [
                    ( PF_BOOL  , "force"      , "Force points", True ),
                    stdopt_filter,
                    stdopt_src,
                    stdopt_dest
                ],
                [],
                plugin_perspective,
                )

register(
                "python_fu_mm_im_rotate",
                "Rotation using path from image and ImageMagick.",
                "Rotation using path from image and ImageMagick.  Select two points which are on a line you want to be either vertical or horizontal.  The plug-in will figure out the rest.",
                "Stephen Geary, ( sg euroapps com )",
                "(c) 2014, Stephen Geary",
                "2014",
                menubase + "Rotation from path",
                "*",
                [
                    stdopt_filter,
                    stdopt_src,
                    stdopt_dest
                ],
                [],
                plugin_rotate,
                )

register(
                "python_fu_mm_im_colordotproduct",
                "Get the dot product of the image and the foreground color using ImageMagick.",
                "Get the dot product of the image and the foreground solor using ImageMagick.",
                "Stephen Geary, ( sg euroapps com )",
                "(c) 2014, Stephen Geary",
                "2014",
                menubase + "Color Dot Product",
                "*",
                [
                    stdopt_src,
                    stdopt_dest
                ],
                [],
                plugin_colordotproduct,
                )
                
register(
                "python_fu_mm_im_colordistance",
                "Get the color distance of the image and the foreground color using ImageMagick.",
                "Get the color distance of the image and the foreground color using ImageMagick.",
                "Stephen Geary, ( sg euroapps com )",
                "(c) 2014, Stephen Geary",
                "2014",
                menubase + "Color Distance",
                "*",
                [
                    stdopt_src,
                    stdopt_dest
                ],
                [],
                plugin_colordistance,
                )

register(
                "python_fu_mm_im_colordistance_lab",
                "Get the color distance of the image and the foreground color using ImageMagick LAB color space.",
                "Get the color distance of the image and the foreground color using ImageMagick LAB color space",
                "Stephen Geary, ( sg euroapps com )",
                "(c) 2014, Stephen Geary",
                "2014",
                menubase + "Color Distance LAB",
                "*",
                [
                    stdopt_src,
                    stdopt_dest
                ],
                [],
                plugin_colordistance_lab,
                )

allspaces = plugin_color_spaces(-1)

register(
                "python_fu_mm_im_colorspace",
                "Covert between color spaces using ImageMagick.",
                "Covert between color spaces using ImageMagick.",
                "Stephen Geary, ( sg euroapps com )",
                "(c) 2014, Stephen Geary",
                "2014",
                menubase + "Color Space Conversion",
                "*",
                [
                    ( PF_OPTION, "spaceto",   "Colorspace Final  :", 0, allspaces ),
                    stdopt_src,
                    stdopt_dest
                ],
                [],
                plugin_colorspaceconversion,
                )

register(
                "python_fu_mm_im_usercommand",
                "Allow user to type in any mogrify command to process the image.",
                "Allow user to type in any mogrify command to process the image.",
                "Stephen Geary, ( sg euroapps com )",
                "(c) 2014, Stephen Geary",
                "2014",
                menubase + "User Command",
                "*",
                [
                    stdopt_src,
                    stdopt_dest,
                    ( PF_TEXT , "arg" , "Command:",     "" )
                ],
                [],
                plugin_usercommand,
                )

register(
                "python_fu_mm_im_list_resources",
                "List image magick resource limits.",
                "List image magick resource limits.",
                "Stephen Geary, ( sg euroapps com )",
                "(c) 2014, Stephen Geary",
                "2014",
                menubase + "Resource Limits",
                "*",
                [
                ],
                [],
                plugin_resource_limits,
                )

##__devcode

if scipy_imported:

    register(
                "python_fu_mm_im_lenscorrection",
                "Lens distortion correction using path from image and ImageMagick.",
                "Lens distortion correction using path from image and ImageMagick.  Not ready for use.",
                "Stephen Geary, ( sg euroapps com )",
                "(c) 2014, Stephen Geary",
                "2014",
                menubase + "Lens Correction/From path (V1)",
                "*",
                [
                    stdopt_filter,
                    stdopt_src,
                    stdopt_dest
                ],
                [],
                plugin_lenscorrection,
                )

    register(
                "python_fu_mm_im_lenscorrection_inverse",
                "Lens distortion correction using path from image and ImageMagick.",
                "Lens distortion correction using path from image and ImageMagick.  Not ready for use.",
                "Stephen Geary, ( sg euroapps com )",
                "(c) 2014, Stephen Geary",
                "2014",
                menubase + "Lens Correction/From path (V2)",
                "*",
                [
                    stdopt_filter,
                    stdopt_src,
                    stdopt_dest
                ],
                [],
                plugin_lenscorrection_inverse,
                )



##__end_devcode

if scipy_imported:

    register(
                "python_fu_mm_im_lc_b",
                "Simple-B Lens distortion correction using path from image and ImageMagick.  You need to select three points on a path which are on something that should be a straight line but is curved in the image.  Model is quadratic.",
                "Simple-B Lens distortion correction using path from image and ImageMagick.  You need to select three points on a path which are on something that should be a straight line but is curved in the image.  Model is quadratic.",
                "Stephen Geary, ( sg euroapps com )",
                "(c) 2014, Stephen Geary",
                "2014",
                menubase + "Lens Correction/Quadratic Model",
                "*",
                [
                    stdopt_filter,
                    stdopt_src,
                    stdopt_dest
                ],
                [],
                plugin_lc_b,
                )

    register(
                "python_fu_mm_im_lc_c",
                "Simple-C distortion correction using path from image and ImageMagick.  You need to select three points on a path which are on something that should be a straight line but is curved in the image.  Correction is to a linear model.",
                "Simple-C distortion correction using path from image and ImageMagick.  You need to select three points on a path which are on something that should be a straight line but is curved in the image.  Correction is to a linear model.",
                "Stephen Geary, ( sg euroapps com )",
                "(c) 2014, Stephen Geary",
                "2014",
                menubase + "Lens Correction/Linear Model",
                "*",
                [
                    stdopt_filter,
                    stdopt_src,
                    stdopt_dest
                ],
                [],
                plugin_lc_c,
                )


main()
  
#----------------------------------------------------------------------------------


