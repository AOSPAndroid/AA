/* Atlas palette bridge. Upstream Draw.io editor and action registry remain intact. */
(function(){
  const init=Actions.prototype.init;
  Actions.prototype.init=function(){
    init.apply(this,arguments);
    const ui=this.editorUi,graph=ui.editor.graph;
    const shapes={atlasProcess:['Process','rounded=1;',180,80],atlasDecision:['Decision?','rhombus;',180,100],atlasTerminal:['Start / end','ellipse;',150,70],atlasDatabase:['Database','shape=cylinder;',140,90],atlasNote:['Note','shape=note;',180,100]};
    Object.entries(shapes).forEach(([name,[label,style,w,h]])=>this.addAction(name,function(){
      if(!graph.isEnabled())return;
      const point=graph.getInsertPoint();
      graph.getModel().beginUpdate();
      let cell;
      try{cell=graph.insertVertex(graph.getDefaultParent(),null,label,point.x,point.y,w,h,style+'whiteSpace=wrap;html=1;fillColor=#e0f2fe;strokeColor=#007fa3;');}
      finally{graph.getModel().endUpdate();}
      graph.setSelectionCell(cell);graph.scrollCellToVisible(cell);
    }));
    this.addAction('atlasConnect',function(){
      const cells=graph.getSelectionCells().filter(c=>graph.getModel().isVertex(c));
      if(cells.length!==2){ui.alert('Select two shapes (Shift-click), then run Connect selected shapes.');return;}
      graph.getModel().beginUpdate();let edge;
      try{edge=graph.insertEdge(graph.getDefaultParent(),null,'',cells[0],cells[1],'edgeStyle=orthogonalEdgeStyle;rounded=0;endArrow=classic;');}
      finally{graph.getModel().endUpdate();}
      graph.setSelectionCell(edge);
    });
  };
})();
