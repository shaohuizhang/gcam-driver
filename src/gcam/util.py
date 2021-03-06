"""Miscellaneous utilities for the GCAM driver."""

import os
import os.path
import re
import string
import subprocess
import tempfile
import random

## utility functions used in other gcam python code

## Place holder for the general params structure.  The constructor for
## that structure knows it's supposed to add itself here.  (TODO: This
## is kind of ugly.  Maybe we should think up a better way to do it.)
## This variable should be considered private to this module
global_params = None
    

## Often we will have to parse values from a config file that are
## meant to indicate a boolean value.  We list here the strings that
## are considered false; everything else is considered true.
def parseTFstring(val):
    """Parse synonyms for "True" and "False" retrieved from the config file."""
    falsevals = ["False", "false", "FALSE", "F", "f", "No", "NO", "N", 
                 "no", "0"]
    return val.lstrip().rstrip() not in falsevals


def rd_rgn_table(filename,skip=1,fltconv=True):
    """Read a csv table of regions and properties.

    The region name should be in the first column.  If there are only
    two columns, then put the result into a dictionary of values by
    region.  If there are more than two columns, put the result into a
    dictionary of lists of values by region.

    Arguments:
      filename - name of the file to process
          skip - number of initial rows to skip (default = 1)
       fltconv - flag: True = convert results to float (DEFAULT); 
                       False = return string values

    Return value: a tuple of two elements.  The first is the table
                   described above.  The second is a list giving the
                   original order of the regions in the file, in case
                   it matters.

    """

    table = {}
    order = []
    with open(filename, "r") as file:
        for sk in range(skip):
            file.readline()

        for line in file:
            line = rm_trailing_comma(line)
            toks = line.split(',')
            rgn  = string.lstrip(string.rstrip(toks[0]))
            data = toks[1:]
            if fltconv:
                data = map(float,data)
            else:
                # Remove leading and trailing whitespace
                data = map(string.lstrip, data)
                data = map(string.rstrip, data)
            if len(data) == 1:
                data = data[0]  # grab the lone value from the list.

            order.append(rgn)
            table[rgn] = data

    return (table, order)
    


## Regular expression for detecting a scenario name (private, used in scenariofix)
scen_pattern = re.compile(r'^"[^"]*"') # Beginning of line, followed by a ", followed
                                       # by any number of non-" chars, followed by a "

def scenariofix(line, newstr="scenario", pat=scen_pattern):
    """Remove commas and excess junk from scenario names.
    
    CSV files returned from the model interface frequently have a
    scenario name as the first field.  The scenario name invariably
    has a comma in it, which really messes up splitting on commas.  We
    almost never use the scenario name for anything, so this function
    transforms it to something benign.

    arguments:
        line   - Line of text read from a GCAM csv output file. 

      newstr   - (arbitrary) string to substitute in place of the
                 scenario field.

         pat   - Regular expression object for detecting a scenario
                 field.  The default value works for the outputs 
                 typically generated by GCAM, so there should be no
                 need to change it; however, if someone produces a 
                 scenario with a sufficiently weird name, a custom
                 pattern can be supplied through this argument.

    """
    return pat.sub(newstr, line)

def gcam_query(batchqfiles, dbxmlfiles, inputdir, outfiles):
    """Run the indicated queries against a dbxml database

    arguments:
      batchqfiles  - List of xml files containing the batch queries to run.  If
                    there is only one, you can just pass the filename.
 
      dbxmlfiles  - List of dbxml file or files to query.  If there is
                    only one, you can just pass the filename.  If
                    there is a list of query files and only a single
                    dbxml, the queries will all be run against the
                    same dbxml.

      inputdir    - Directory where the gcam-driver input files are located.
                    This will typically be provided by the 'general' module.

      outfiles    - List of output files.  should be the same length as
                    the query list.

    """

    if hasattr(batchqfiles,'__iter__') and not isinstance(batchqfiles, str):
        qlist = batchqfiles
    else:
        qlist = [batchqfiles]

    if hasattr(dbxmlfiles, '__iter__') and not isinstance(batchqfiles, str):
        dbxmllist = dbxmlfiles
        if len(dbxmllist) == 1:
            dbxmllist = dbxmllist*len(qlist)
    else:
        dbxmllist = [dbxmlfiles]*len(qlist)

    if hasattr(outfiles, '__iter__') and not isinstance(batchqfiles, str):
        outlist = outfiles
    else:
        outlist = [outfiles]

    ## check for agreement in lengths of the above lists
    if len(dbxmllist) != len(qlist) or len(outlist) != len(qlist):
        raise RuntimeError("Mismatch in input lengths for gcam_query.") 

    genparams      = global_params.fetch()
    ModelInterface = genparams["ModelInterface"]
    DBXMLlib       = genparams["DBXMLlib"]
        
    ### start up the virtual frame buffer.  The Model Interface needs
    ### this even though it won't be displaying anything.
    
    ## We need to select a random display number to avoid collisions
    ## if we're running several driver instances concurrently.
    ## Display numbers up to 1024 seem to be safe.
    random.jumpahead(os.getpid()) # make sure that different instances have different rng states.
    disp = random.randint(1,1024)
    print 'X display is: %d' % disp
    xvfb = subprocess.Popen(['Xvfb', ':%d'%disp, '-pn', '-audit', '4', '-screen', '0', '800x600x16'])
    try:
        ldlibpath = os.getenv('LD_LIBRARY_PATH')
        if ldlibpath is None:
            ldlibpath = "LD_LIBRARY_PATH=%s"%DBXMLlib
        else:
            ldlibpath = "LD_LIBRARY_PATH=%s:%s" % (ldlibpath,DBXMLlib) 

        for (query, dbxml, output) in zip(qlist,dbxmllist,outlist):
            print query, output
            ## make a temporary file
            tempquery = None
            try:
                tempquery = rewrite_query(query, dbxml, inputdir, output)
                execlist = ['/bin/env', 'DISPLAY=:%d.0'%disp, ldlibpath, 'java', '-jar',
                            ModelInterface, '-b', tempquery]

                subprocess.call(execlist)

            finally:
                if tempquery:
                    os.unlink(tempquery)
    finally:
        xvfb.kill()

    ## output from these queries goes into csv files.  The names of
    ## these files are in the query file, so it's up to the caller to
    ## know or figure out where its data will be.
    return outlist              # probably redundant, since the list of output files was an argument.


### Some regular expressions used in query_file_rewrite (private):
xmldbloc   = re.compile(r'<xmldbLocation>.*</xmldbLocation>')
outfileloc = re.compile(r'<outFile>.*</outFile>')
qfileloc   = re.compile(r'<queryFile>(.*)</queryFile>')

def rewrite_query(query, dbxml, inputdir, outfile):
    """Rewrite dbxml query file to include the names of the dbxml file and output file and location of query file.

    The names of the input dbxml and output csv files are encoded in
    the query file.  Since we want to be able to set them, we need to
    treat the query file as a template and create a temporary with the
    real file names.  This function creates the temporary and returns
    its name.

    Arguments:
      query  - The 'batch query file'.  This is, unfortunately, not the
               same file as the 'query file', which is mentioned inside
               the 'batch query file'.
      dbxml  - The gcam database output file to run the query against
      inputdir - The location (directory) of the 'query file'.  Generally
               this will be the 'input-data' directory under the gcam-driver
               top-level directory.
     outfile - Name of the output file to put the results in.

    """
    (fd, tempqueryname) = tempfile.mkstemp(suffix='.xml') 

    ## copy the input query file line by line into the temp
    ## file; however, edit the xmldb and output locations to
    ## match the arguments.
    origquery = open(query,"r")
    tempquery = os.fdopen(fd,"w")

    dbxmlstr = '<xmldbLocation>' + dbxml + '</xmldbLocation>'
    outfilestr = '<outFile>' + outfile + '</outFile>'

    for line in origquery:
        ## replace xml db file name
        line = xmldbloc.sub(dbxmlstr, line)
        ## replace output file name
        line = outfileloc.sub(outfilestr, line)
        ## replace query file name.  This one is a bit more
        ## complicated, as we have to get the base name of the file
        ## from the template
        qfile_match = qfileloc.search(line)
        if(qfile_match):
            ## get the filename
            qfile_template = qfile_match.group(1)
            ## strip off the (probably bogus) directory path and
            ## replace with inputdir
            qfile = os.path.basename(qfile_template)
            qfile = abspath(qfile,defaultpath=inputdir)
            line = '<queryFile>%s</queryFile>'%qfile
        
        tempquery.write(line)

    tempquery.close()
    return tempqueryname

        
## regex for removing trailing commas
## TODO:  Do we need to remove multiple trailing commas?
_trlcomma = re.compile(r',\s*$')
def rm_trailing_comma(line):
    """Remove trailing comma, if any, from a string."""
    return _trlcomma.sub('',line)

## remove trailing whitespace
## TODO:  this could probably be merged with the function above
_trlspc = re.compile(r'\s*$')
def chomp(astring):
    """Remove trailing whitespace, if any, from a string."""
    return _trlspc.sub('',astring)

def allexist(files):
    """Test a list of files to determine whether all exist."""
    allfiles = True
    for file in files:
        if not os.path.exists(file):
            allfiles = False
            break
    return allfiles

def abspath(filename,defaultpath=None, tag=None):
    """Convert a filename to an absolute path.

    Names starting with '/' are returned unchanged.  Names beginning
    with './' or '../' are always assumed to be relative to the current
    directory.  All others are assumed to be relative to a supplied
    default, or to the current directory if none is supplied.

    Arguments:
         filename - filename to convert 
      defaultpath - default base for relative paths.  (OPTIONAL - If
                    not given, then it is an error to specify a
                    filename relative to the (non-existent) default
                    path.)

    """

    print '[%s]: default path= %s  filename= %s' % (str(tag), str(defaultpath), str(filename))

    if filename[0] == '/':
        return filename
    elif defaultpath is None or filename[0:2] == './' or filename[0:3]=='../':
        return os.path.abspath(filename)
    else:
        return os.path.join(defaultpath,filename)

def mkdir_if_noexist(dirname):
    """Create a directory, if it doesn't exist already.

    This function will create the specified directory, along with any
    intermediate directories, if they don't already exist.  If the
    directory already exists, nothing is done.  If the directory
    doesn't exist, and can't be created, an exception is raised.  The
    directory will be created with the default access mode of 0777,
    which will be modified by the current umask in the usual way.

    Arguments:
        dirname - Name of the directory to create

    Return value:  none

    Exceptions:
      OSError - The directory doesn't exist but can't be created.
                Usually this means that either a non-directory 
                file type already exists at that name, or some 
                intermediate directory is not writeable by this UID.

    Limitations:  If the directory already exists, this function 
                  does not check to see if it is readable or
                  writeable by this UID.
    """

    try:
        os.makedirs(dirname)
    except OSError:
        if os.path.isdir(dirname):
            pass
        else:
            raise
