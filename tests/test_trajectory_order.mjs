import {test} from 'node:test';
import assert from 'node:assert/strict';
import {trajectoryTurns} from '../src/trajectory-order.js';

const flatten=turns=>turns.flatMap(turn=>turn.groups.flatMap(group=>group.cells.map(cell=>cell.recordId)));
test('a repeated group cannot move the current question ahead of replayed history',()=>{
  const cells=[
    {recordId:'context',rowId:'request',turn:1,group:'current'},
    {recordId:'hi',rowId:'request',turn:1,group:'history'},
    {recordId:'answer-hi',rowId:'request',turn:1,group:'history'},
    {recordId:'test',rowId:'request',turn:1,group:'history'},
    {recordId:'answer-test',rowId:'request',turn:1,group:'history'},
    {recordId:'continue',rowId:'request',turn:1,group:'current'},
    {recordId:'answer-continue',rowId:'request',turn:1,group:'current'},
  ];
  assert.deepEqual(flatten(trajectoryTurns(cells)),cells.map(cell=>cell.recordId));
  assert.deepEqual(trajectoryTurns(cells)[0].groups.map(group=>group.title),['current','history','current']);
});
test('interleaved turns stay in event order instead of being bucketed together',()=>{
  const cells=[{recordId:'main-start',rowId:'one',turn:1,group:'step'},
    {recordId:'child',rowId:'two',turn:2,group:'step'},
    {recordId:'main-end',rowId:'three',turn:1,group:'step'}];
  assert.deepEqual(flatten(trajectoryTurns(cells)),['main-start','child','main-end']);
  assert.deepEqual(trajectoryTurns(cells).map(turn=>turn.turn),[1,2,1]);
});
test('restored conversation turns remain before the current third turn',()=>{
  const cells=[{recordId:'instructions',rowId:'request',turn:null,group:'instructions'},
    {recordId:'environment',rowId:'request',turn:1,group:'current'},
    {recordId:'hi',rowId:'request',turn:1,group:'history'},
    {recordId:'hi-reply',rowId:'request',turn:1,group:'history'},
    {recordId:'test',rowId:'request',turn:2,group:'history'},
    {recordId:'test-reply',rowId:'request',turn:2,group:'history'},
    {recordId:'continue',rowId:'request',turn:3,group:'current'},
    {recordId:'continue-reply',rowId:'request',turn:3,group:'current'}];
  assert.deepEqual(flatten(trajectoryTurns(cells)),cells.map(cell=>cell.recordId));
  assert.deepEqual(trajectoryTurns(cells).map(turn=>turn.turn),[null,1,2,3]);
});
