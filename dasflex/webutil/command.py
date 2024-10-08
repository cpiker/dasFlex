"""Helpers for running sub-commands"""

import sys
import subprocess
import select
import fcntl
import os
import re
from copy import deepcopy

import das2

from . import webio
from . import errors as E
from . import mime

# ########################################################################## #

def _sameType(paramVal, trigVal):
	"""Helper for cmdTriggered.  Handles type coersion for comparison purposes.

	returns (varies, varies)
		Always tries for non-string types if possible, default to strings if
		float does not work.
	"""
	
	try:
		_retParam = float(paramVal)
		_retTrig  = float(trigVal)
	except:
		_retParam = str(paramVal)
		_retTrig = str(trigVal)

	return (_retParam, _retTrig)


def cmdTriggered(fLog, sCmd, dCmd, dParams):
	"""Determine if a particular command has been triggered by the given
	http parms.  If the command does not have a 'trigger' section the default
	is to auto-trigger.
	Args:
		fLog (file-like) - A logger object with a .write method
		sCmd (str) - The name of the command
		dCmd (dict) - A command object
		dParams (dict) - A key value dictionaly, presumably from a form submission
	"""

	if 'activation' not in dCmd:
		fLog.write("   INFO: Command %s always runs"%dCmd['label'])
		return True

	lTriggers = dCmd['activation']

	# Using implicit AND for now, so all triggers must be tripped

	nRequired = len(lTriggers)
	nTripped = 0
	for dTrig in lTriggers:
		if 'key' not in dTrig:
			fLog.write("   ERROR: 'key' missing from command object activation")
			continue

		if dTrig['key'] not in dParams: continue

		if 'value' not in dTrig:
			if dTrig['key'] in dParams:
				nTripped += 1
		else:
			# Try type coersion
			value, trigger = _sameType(dParams[dTrig['key']], dTrig['value'])

			if ('compare' not in dTrig) or (dTrig['compare'] == 'eq'):
				if value == trigger:
					nTripped += 1
			else:
				if dTrig['compare'] == 'gt':
					if value > trigger:
						nTripped += 1
				elif dTrig['compare'] == 'lt':
					if value < trigger:
						nTripped += 1
				elif dTrig['compare'] == 'ge':
					if value >= trigger:
						nTripped += 1
				elif dTrig['compare'] == 'le':
					if value <= trigger:
						nTripped += 1
				elif dTrig['compare'] == 'ne':
					if value != trigger:
						nTripped += 1
				else:
					fLog.write("   INFO: Command activation comparison '%s' is unknown"%dTrig['compare'])

	sStatus = "does not run."
	if (nTripped == nRequired):
		sStatus = "added to pipeline."

	fLog.write("   INFO: %d of %d conditions met for command %s, %s"%(
		nTripped, nRequired, sCmd, sStatus
	))

	return (nTripped == nRequired)

# ########################################################################## #
def triggered(fLog, dSrc, dParams):
	"""Look through the commands section of an internal source description
	and determine the commands that should be enabled.   Each command has an
	order in the internal.json file.  If two commands of the same order are
	triggered then the query solution is inconclusive.

	Args:
		fLog (file-like): An object with a .write method for logging
		dSrc (dict): An internal source dictionary (aka an internal.json)
		dParam (dict): A key = value dictionary of request parameters

	Returns (list, None):
		A list of command objects in the order in which they should be invoked
		in a command pipeline.  If two or more objects are to be invoked in
		the same order then and error is logged, and None is returned.

	Exceptions:
		ServerError - Raised if required information is missing from source def

		QueryError  - Raised if the given parameter set can't resolve to a 
		  unique command line.

	If a single category has more then one triggered command: None is returned
	and a message is logged to 
	"""

	if 'commands' not in dSrc:
		raise E.ServerError("No command section present in source definition.")

	dCmds = dSrc['commands']

	# First check that at least one of the commands does not contain in input
	# (aka it's a true data source)
	bHaveSrc = False
	for dCmd in dCmds:
		if 'input' not in dCmd:
			bHaveSrc = True
			break

	if not bHaveSrc:
		raise E.ServerError("No upstream data source (aka reader) present in source definition")

	# Each item is a list, keys are the order.  To be valid, the first command
	# to run must not require an input, and there must be no more then one command 
	# by order.
	dTrig = {}
	
	# Set up the list of possible commands by order
	dOrder = {}
	for sCmd in dCmds:
		dCmd = dCmds[sCmd]
		if 'order' not in dCmd:
			raise E.ServerError("'order' parameter missing in command definition")

		nOrder = int(dCmd['order'])
		if nOrder not in dOrder:
			dOrder[nOrder] = {}

		dOrder[nOrder][sCmd] = dCmd

	lOrder = list(dOrder.keys())
	lOrder.sort()
	lOrder.reverse()

	# Going in backwards order, activate commands.  Later commands can change
	# the parameters via "set".

	_dParams = deepcopy(dParams) # Higher level can set params for lower levels

	for nOrder in lOrder:  # Reversed above
		dCmdLvl = dOrder[nOrder]

		# First pass at this level, activate anything here
		for sCmd in dCmdLvl:
			if cmdTriggered(fLog, sCmd, dCmdLvl[sCmd], _dParams):
				if nOrder in dTrig: dTrig[nOrder].append(dCmdLvl[sCmd])
				else:               dTrig[nOrder] = [dCmdLvl[sCmd]]

		# Second pass at this level, set any params for lower levels
		if nOrder in dTrig:
			for dCmd in dTrig[nOrder]:
				if "set" in dCmd:
					for dSet in dCmd["set"]:
						if "key" in dSet:
							if "value" in dSet: 
								_dParams[dSet["key"]] = dSet["value"]
							else:
								_dParams[dSet["key"]] = True
							fLog.write("   INFO: %s sets %s=%s for level %d and lower commands"%(
								dCmd['label'],dSet["key"],_dParams[dSet["key"]], nOrder - 1
							))

	# If nothing triggered, we have a problem
	if len(dTrig) == 0:
		raise E.QueryError("Query parameters did not cause any data sources to run")

	# Write a list of triggered items, making sure each level is unique
	lTrig = []
	lOrder = list(dTrig.keys())
	lOrder.sort()
	for nOrder in lOrder:
		if len(dTrig[nOrder]) > 1:
			raise E.QueryError(
				"Query did not resolve to a unique pipeline. "+\
				"Multiple commands at order %d."%nOrder
			)
		else:
			lTrig.append(dTrig[nOrder])

	# Now make sure the first item dosen't have an input mime type.
	if 'input' in lTrig[0]:
		raise E.ServerError("No upstream data source readers were activated by this query")

	lOut = [ dTrig[nOrder][0] for nOrder in lOrder]

	if len(lOut) == 0:
		raise E.QueryError("Query did not trigger any local processing")

	if 'input' in lOut[0]:
		raise E.QueryError(
			"Invalid query, upstream data producer not triggered, command"+\
			" pipeline is '%s'"%("'->'".join(d['label'] for d in lOut))
		)

	return lOut


# ########################################################################## #
# The Template list to command pipeline generator                            #

def _subForPtrn(fLog, sTemplate, dParams):
	"""
	Args:
		fLog (file-like) - Logger
		sTemplate (str) - The template guiding the replacement procedure
		dParms (dict) - An HTTP GET query dictionary

	Returns (str): A string to substitue for the pattern.  A length 0 string
		is as valid output, but None is not.
	"""

	nFlags = re.ASCII | re.VERBOSE

	# Break replacement sections into a selector, pattern if present, pattern if not
	mFull = re.fullmatch(r'''
		(\#\[[a-zA-Z][a-zA-Z0-9_:\.\\\-\(\)=\ |]*) # Manditory primary GET parameter
		(\#[' "a-zA-Z0-9_:,\.\-@]+)?                 # optional substitution if present
		(\#[' "a-zA-Z0-9_:,\.\-@]*)?                  # optional substitution if not present
		(\])                                       # Manditory end bracket
	''', sTemplate, flags=nFlags)

	if mFull == None:
		raise E.ServerError("Match error in subsitution pattern '%s'"%sTemplate)

	lSub = list(mFull.groups())
	lSub[0] = lSub[0][2:]   # knock off '#['
	(sSelector, sPresent, sAbsent) = (lSub[0], None, None)

	if (len(lSub) > 1) and lSub[1]: 
		sPresent = lSub[1][1:] # knock off the #
	else:
		sPresent = '@'
	if len(lSub) > 2 and lSub[2]: 
		sAbsent  = lSub[2][1:] # knock off the #

	# lacking an if-absent output means param is manditory
	
	# Break out the sub-selector
	mParam = re.fullmatch(r'''
		([a-zA-Z][a-zA-Z0-9:_\.\-]*)         # Manditory primary GET parameter
		(\([a-zA-Z0-9= ,:;_\.\\\-\|]*?\))?   # optional sub-selection if present
		''', sSelector, flags=nFlags
	)

	lSelector = list(mParam.groups())
	(sSubSep, sSubSel, sSubValSep) = (None, None, None) 

	if (len(lSelector) > 1) and lSelector[1]:
		# Have sub-selector, parse it
		mSubSel = re.fullmatch(r'''
			(?:\()                  # match but ignore paren
			([:;,_\.\+\- ]*)        # key,value pair separator 
			(?:\|)                  # match but ignore pipe
			([a-zA-Z0-1=_\-]+)      # sub key to watch for
			(\|[=:;,_\.\+\- ]*)?    # optional sub-key to sub-val separator
			(?:\))                  # match but ignore close paren
		''', lSelector[1], flags=nFlags)

		lSubSel = list(mSubSel.groups())
		if len(lSubSel) < 2:
			raise E.ServerError("Malformed sub param selector parameter in '%s'"%sSelector)
		sSubSep = lSubSel[0]
		sSubSel = lSubSel[1]

		if len(lSubSel) > 2: sSubValSep = lSubSel[2][1:]

		sSelector = lSelector[0] # Only the first part is the outer parameter

	# Now that I have all the parts, find my parameter
	if sSelector not in dParams:
		if sAbsent != None:
			return sAbsent
		else:
			fLog.write("Command template '%s' requires parameter '%s' which was not supplied"%(
				sTemplate, sSelector)
			)
			raise E.QueryError("Missing query parameter '%s'"%sSelector)

	sValue = dParams[sSelector]  # Empty string is okay, None is not

	# If I have a sub-selector, break down the param value and do sub-parsing
	# Just look for the value of interest, don't create sub parsing dictionary.
	if sSubSel:
		fLog.write("   INFO: Subselect of '%s' ('%s'|'%s'|'%s')"%(sSelector, sSubSep, sSubSel, sSubValSep))
	
		sSubVal = None
		if sValue:
			if sSubSep:  # I can tokenize the value
				lSub = sValue.split(sSubSep)

				for sChunk in lSub:
					if sChunk.startswith(sSubSel):  # I have the start of it
						if sSubValSep:
							lChunk = sChunk.split(sSubValSep)
							if len(lChunk)	> 0:
								sSubVal = sSubValSep.join(lChunk[1:])
						else:
							sSubVal = sSubSel  # Treat as a flag
						break

			else: # I cannot tokenize the value, use the param itself as the value
				if sValue.find(sSubSel) != -1:
					sSubVal = sSubSel

		if sSubVal == None:
			if sAbsent != None:
				return sAbsent
			else:
				fLog.write("Command template '%s' requires sub-parameter '%s' which was not supplied"%(
					sTemplate, sSubSel)
				)
				raise E.QueryError("Missing sub-query parameter '%s'"%sSubSel)
		else:
			sValue = sSubVal
			sSelector = sSubSel
		
	# Should have a value now
	if len(sValue) > 0:
		return sPresent.replace( '@', '%s'%sValue)
		
	return ""



def substitute(fLog, sFullTplt, dParams):
	"""Subtitute query parameters into a command template to generate a
	single command.  Used by the pipeline creator.

	In general the parameter intepretation is complex enough that it can handle
	sub-parameters cammed into a single GET parameter. See:
	
	  docs/CmdTemplates.md

	in the general source distribution for a full description.

	Args:
		fLog - Anything with a write() method that auto-adds newlines
		sTemplate - The command template to substitute
		dParams - A key=value dictionary of parameters.

	Returns (str): A string with with all subtitutions inserted, or None
		if an error occured.  Specific error message is logged.
	"""

	lAccum = []

	# Tired of regex...
	sRemain = sFullTplt
	while len(sRemain) > 0:
		i = sRemain.find('#[')
		if i == -1:
			lAccum.append(sRemain)
			break
		else:
			lAccum.append(sRemain[:i])
			sRemain = sRemain[i:]

		# At this point start of string should be a selector sub pattern
		i = sRemain.find(']')
		if i == -1:
			raise E.ServerError("Param substitution section not closed in '%s'"%sTemplate)

		sPtrn = sRemain[:i+1]
		sRemain = sRemain[i+1:]

		lAccum.append( _subForPtrn(fLog, sPtrn, dParams) )

	return ''.join(lAccum)


def pipeline(fLog, lCmds, dParams):
	"""Substitue query parameters into command templates to generate a shell
	pipeline.  A wrapper around substitute makes a single pipelined command

	Args:
		fLog - Something with a .write method that adds a newline for each call
		lCmds - A *ordered* command list
		dParams - The HTTP GET params dictionary.
	"""
	lOut = []
	for dCmd in lCmds:
		if 'template' not in dCmd:
			raise E.ServerError("Invalid source definition, 'template' section missing")

		if isinstance(dCmd['template'], list):
			sTemplate = ' '.join(dCmd['template'])
		elif isinstance(dCmd['template'], str):
			sTemplate = dCmd['template']
		else:
			raise E.ServerError("Invaild data type for 'template' section, exected list or string")

		sSub = substitute(fLog, sTemplate, dParams)
		if len(sSub) > 0:
			lOut.append( sSub )

	sPipeline = ' | '.join(lOut)
	#fLog.write("   EXEC: %s"%sPipeline)
	return sPipeline

# ########################################################################## #

def _fileDasTime(dt):
	lName = []
	
	lName.append("%04d-%02d-%02d"%(dt.year(), dt.month(), dt.dom() ))
	if (dt.hour() > 0) or (dt.minute() > 0) or (dt.sec() > 0.0):
		lName.append('T')
		lName.append("%02d-%02d"%(dt.hour(), dt.minute()))
		if dt.sec() > 0.0:
			lName.append("-%02d"%(dt.sec()))	

	return "".join(lName)

def _isorange(fLog, lArgs):
	"""Given arguments that are supposedly start time and stop time output
	a time stamp suitable for use in a filename.
	"""

	if len(lArgs) == 0:
		return ""

	dtBeg = das2.DasTime(lArgs[0])

	lName = []
	if (len(lArgs) == 1) or (lArgs[1] == 'forever'):
		lName.append(_fileDasTime(dtBeg))
	else:
		# If we get two arguments
		lName.append(_fileDasTime(dtBeg))
		dtEnd = das2.DasTime(lArgs[1])
		if (dtEnd - dtBeg) != 86400.0:  # Just a daily coverage file
			lName.append('_')
			lName.append(_fileDasTime(dtEnd))

	return "".join(lName)

def _normparams(fLog, lArgs):
	"""Normalize a set of arguments in a way that's suitable for use in a 
	filename
	"""

	return "FixMeParams"

def _timeres(fLog, lArgs):
	"""Given arguments that supposedly set a time range in seconds, provide
	a filename token representing the range.

	The expected args are:  
		[ 
			prefix if successful, requested resolution, option units
		]
	"""

	if len(lArgs) < 2:
		return ""

	if (len(lArgs[1]) == 0) or (not lArgs[1]):
		return ""

	try:
		f = float(lArgs[1])
	except Exception as e:
		fLog.write(
			"ERROR: couldn't convert %s to a float in text function _timeres()"%lArgs[1]
		)
		return "binned"

	if f > 2*86400:
		s = "bin-%.2f"%(f/86400)
		sUnit = 'day'
	elif f > 2*3600:
		s = "bin-%.2f"%(f/3600)
		sUnit = 'hr'
	elif f > 2*60:
		s = "bin-%.2f"%(f/60)
		sUnit = 'min'
	else:
		s = "bin-%.2f"%f
		sUnit = "s"

	if s[-3:] == ".00": s = s[:-3]

	return "%s%s%s"%(lArgs[0], s, sUnit)


# ########################################################################## #

def filename(fLog, dConf, dParams, lTranslate, dTarg):
	"""Given a translation template and the GET parameters, provide a decent
	default filname for a data query since humans like it when the computer
	picks reasonable names for them.

	Args:
		fLog (file-like) - A object with a .write() method that adds newlines
		
		dConf (dict) - Server configuration

		dParams (dict) - A query parameter dictionary

		lTranslate (list of dict) - A translation list

		dTarg (dict) - A data type dictionary, here's an example   
		       {'type':'das','version':'2.2','variant':'text'}

	Returns (str, str, str):  Which are the strings:
		* The mimetype of the data
		* The content disposition, ['attachment'|'inline']
		* A default filename.

	"""
	lName = []

	for dCall in lTranslate:
		if ('function' not in dCall) or ('args' not in dCall):
			raise E.ServerError("Invalid filename creation procedure")

		lArgs = []
		for sArg in dCall['args']:
			if len(sArg) == 0: continue

			if sArg[0] == "#":
				lArgs.append(substitute(fLog, sArg, dParams))
			else:
				lArgs.append(sArg)

		sFunc = dCall['function']

		if sFunc == 'echo':
			lName.append("".join(lArgs))
		elif sFunc == 'isorange':
			lName.append(_isorange(fLog, lArgs))
		elif sFunc == 'normparams':
			lName.append(_normparams(fLog, lArgs))
		elif sFunc == 'timeres':
			lName.append(_timeres(fLog, lArgs))
		else:
			raise E.ServerError("Unknown text transform function '%s' in source definition"%sFunc)

	sName = "".join(lName)

	# Now get the mime type
	dMimes = mime.load(dConf)
	sType, sVer, sVar = None, None, None
	if 'type' in dTarg: sType = dTarg['type']
	if 'version' in dTarg: sVer = dTarg['version']
	if 'variant' in dTarg: sVar = dTarg['variant']

	(sMime, sExt, sTitle) = mime.get(dMimes, sType, sVer, sVar)
	sName = "%s.%s"%(sName,sExt)

	fLog.write("Output MIME is: %s"%sMime)

	if sMime.startswith('text/') and (not sMime.startswith('text/csv')):
		sDisp = 'inline'
	else:
		sDisp = 'attachment'

	return (sMime, sDisp, sName)

# ########################################################################## #
def sendCmdOutput(fLog, uCmd, sMimeType, sContentDis, sOutFile):
	"""Send the output of a command pipeline as an HTTP message body.
	
	Standard output is sent on as an http message body, standard error
	output is spooled and send back to the caller.  Output is:
	
	   ( return_code,  stderr_output, hdrs_flag, output_flag)
		
	return_code - The value returned by the sub-shell that can the command
	
	stderr_output - A string containing the output of the standard error
	                channel form the sub-command
	
	hdrs_flag  - This is true if any HTTP headers have already been sent,
	             false otherwise.

	any_out - This is true if any message body output was generated at all
	
	NOTE: This handles writing HTTP Headers AND the response body.
	"""
	
	# We can't output the HTTP headers until we know that running program
	# doesn't produce an error.  But we don't want to buffer all the data
	# until it finishes.
	
	# Solution: Check the 1st non-zero read from stdout, if it starts
	# with anything that looks like <stream> then you're good, say it's data
	
	# Change shell=False, and fix fillDsdfDefaults to work on windows
	proc = subprocess.Popen(uCmd, shell=True, stdout=subprocess.PIPE, 
	                        stderr=subprocess.PIPE, bufsize=-1)
	
	fdStdOut = proc.stdout.fileno()
	fdStdErr = proc.stderr.fileno()
	
	fl = fcntl.fcntl(fdStdOut, fcntl.F_GETFL)
	fcntl.fcntl(fdStdOut, fcntl.F_SETFL, fl | os.O_NONBLOCK)
	
	fl = fcntl.fcntl(fdStdErr, fcntl.F_GETFL)
	fcntl.fcntl(fdStdErr, fcntl.F_SETFL, fl | os.O_NONBLOCK)
	
	bBreakNext = False
	bHttpHdrsSent = False
	lStdErr = []
	bAnyOutput = False
		
	while True:
		lReads = [fdStdOut, fdStdErr]
		lReady = select.select(lReads, [], [])
		
		for fd in lReady[0]:
			
			if fd == fdStdOut:
				xRead = proc.stdout.read()
				if len(xRead) != 0:
					
					if not bHttpHdrsSent:
						webio.pout('Access-Control-Allow-Origin: *\r\n')
						webio.pout('Access-Control-Allow-Methods: GET\r\n')
						webio.pout('Access-Control-Allow-Headers: Content-Type\r\n')	
						webio.pout("Content-Type: %s\r\n"%sMimeType)
						webio.pout("Status: 200 OK\r\n")
						webio.pout("Expires: now\r\n")
						webio.pout('Content-Disposition: %s; filename="%s"\r\n\r\n'%(
						      sContentDis, sOutFile))
						webio.flushOut()
						bHttpHdrsSent = True
					
					webio.pout(xRead)
					webio.flushOut()
					bAnyOutput = True
				
			if fd == fdStdErr:
				xRead = proc.stderr.read()
				if len(xRead) != 0:
					#fLog.write(xRead)
					lStdErr.append(xRead)
		
		if bBreakNext:
			break
		
		if proc.poll() != None:
			# Go around again to make sure we have read everything
			bBreakNext = True
	
	if not bAnyOutput:  # If command could not send anything at least send hdrs
		if proc.returncode == 0:
			fLog.write("WARNING: Successful command did not produce any output")
		else:
			fLog.write("ERROR: Failed command did not produce any output")

	fLog.write("Finished Read")
	
	if sys.version_info[0] == 2:
		sStdErr = ''.join(lStdErr)
	else:
		xStdErr = b''.join(lStdErr)
		sStdErr = xStdErr.decode('utf-8')
	
	return (proc.returncode, sStdErr, bHttpHdrsSent, bAnyOutput)

##############################################################################
# Suitable for commands that should produce a few KB of output

def getCmdOutput(fLog, uCmd):
	"""run a command and get it's return code, standard output and standard
	error.  This buffers the entire output in memory, so don't use this if
	a large amount of output is expected.
	"""
	
	proc = subprocess.Popen(uCmd, shell=True, stdout=subprocess.PIPE, 
	                        stderr=subprocess.PIPE, bufsize=-1)
	
	fdStdOut = proc.stdout.fileno()
	fdStdErr = proc.stderr.fileno()
	
	fl = fcntl.fcntl(fdStdOut, fcntl.F_GETFL)
	fcntl.fcntl(fdStdOut, fcntl.F_SETFL, fl | os.O_NONBLOCK)
	
	fl = fcntl.fcntl(fdStdErr, fcntl.F_GETFL)
	fcntl.fcntl(fdStdErr, fcntl.F_SETFL, fl | os.O_NONBLOCK)
	
	bBreakNext = False
	lStdOut = []
	lStdErr = []
	while True:
		lReads = [fdStdOut, fdStdErr]
		lReady = select.select(lReads, [], [])
		
		for fd in lReady[0]:
			
			if fd == fdStdOut:
				xRead = proc.stdout.read()
				if len(xRead) != 0:
					lStdOut.append(xRead)
				
			if fd == fdStdErr:
				xRead = proc.stderr.read()
				if len(xRead) != 0:
					fLog.write(xRead)
					lStdErr.append(xRead)
		
		if bBreakNext:
			break
		
		if proc.poll() != None:
			# Go around again to make sure we have read everything
			bBreakNext = True
	
	
	fLog.write("Finished Read")
	
	if sys.version_info[0] == 2:
		sStdErr = "".join(lStdErr)
		sStdOut = "".join(lStdOut)
	else:
		xStdErr = b''.join(lStdErr)
		xStdOut = b''.join(lStdOut)
		sStdErr = xStdErr.decode('utf-8')
		sStdOut = xStdOut.decode('utf-8')
	
	return (proc.returncode, sStdOut, sStdErr)
