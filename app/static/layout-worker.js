'use strict';
importScripts('/vendor/d3-7.9.0.min.js','/vendor/dagre-1.1.5.min.js','/layout-engine.js');
self.onmessage=event=>{
  try {const result=calculateLayout(event.data,d3,dagre,percent=>self.postMessage({percent}));self.postMessage({result});}
  catch(error){self.postMessage({error:error.message});}
};
