/*
 *  OSSMTimeValue_g.h
 *  gnome
 *
 *  Created by Generic Programmer on 10/20/11.
 *  Copyright 2011 __MyCompanyName__. All rights reserved.
 *
 */

#ifndef __OSSMTimeValue_g__
#define __OSSMTimeValue_g__

#include "Earl.h"
#include "TypeDefs.h"
#include "OSSMTimeValue_b.h"
#include "TimeValue/TimeValue_g.h"

class OSSMTimeValue_g : virtual public OSSMTimeValue_b, virtual public TimeValue_g { 
	
public:
	
	virtual OSErr			InitTimeFunc ();
	virtual OSErr 			MakeClone(TClassID **clonePtrPtr);
	virtual OSErr 			BecomeClone(TClassID *clone);
	
	virtual OSErr			ReadTimeValues (char *path, short format, short unitsIfKnownInAdvance);
	OSErr 			ReadHydrologyHeader (char *path);
	virtual ClassID 		GetClassID () { return TYPE_OSSMTIMEVALUES; }
	virtual Boolean			IAm(ClassID id) { if(id==TYPE_OSSMTIMEVALUES) return TRUE; return TimeValue_g::IAm(id); }
	
	virtual void 			GetTimeFileName (char *theName) { strcpy (theName, fileName); }
	
	virtual short			GetFileType	() { if (fFileType == PROGRESSIVETIDEFILE) return SHIOHEIGHTSFILE; else return fFileType; }
	virtual void			SetFileType	(short fileType) { fFileType = fileType; }
	
	// I/O methods
	virtual OSErr 			Read  (BFPB *bfpb);  // read from current position
	virtual OSErr 			Write (BFPB *bfpb);  // write to  current position
	
	virtual long 			GetListLength ();
	virtual ListItem 		GetNthListItem 	(long n, short indent, short *style, char *text);
	virtual Boolean 		ListClick 	  	(ListItem item, Boolean inBullet, Boolean doubleClick);
	virtual Boolean 		FunctionEnabled (ListItem item, short buttonID);
	
	virtual OSErr 			CheckAndPassOnMessage(TModelMessage *message);
	
};

#endif