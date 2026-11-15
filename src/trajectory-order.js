// Preserve the projected event order, including repeated turn/group segments.
export function trajectoryTurns(cells){
  const sections=[];
  for(const cell of cells){
    const key=cell.turn??`between:${cell.rowId}`;
    let section=sections[sections.length-1];
    if(!section||section.key!==key){section={key,turn:cell.turn,groups:[]};sections.push(section);}
    let group=section.groups[section.groups.length-1];
    if(!group||group.title!==cell.group){group={title:cell.group,cells:[]};section.groups.push(group);}
    group.cells.push(cell);
  }
  return sections.map(({turn,groups})=>({turn,groups}));
}
