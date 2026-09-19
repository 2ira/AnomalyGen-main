#!/usr/bin/env python3
"""
Build the 40-merge-point path-feasibility benchmark for HDFS.

Combines CFG path definitions, source-code extraction, and manual ground
truth into a single JSONL dataset at eval_data/feasibility_manual.jsonl.

Split: 28 simple (17 feasible + 11 infeasible)
       12 complex (8 feasible + 4 infeasible)

Usage:
    python eval_phase2/build_feasibility_dataset.py [--repo /path/to/AnomalyGen-main]
"""
import json
import os
import re
import argparse

HERE = os.path.dirname(os.path.abspath(__file__))
EVAL_DATA = os.path.join(HERE, "eval_data")
os.makedirs(EVAL_DATA, exist_ok=True)


# ═════════════════════════════════════════════════════════════════════════
# Source-code extraction helpers
# ═════════════════════════════════════════════════════════════════════════
def extract_method(filepath, method_name, max_lines=100):
    """Extract a Java method body by name, truncating if needed."""
    if not os.path.exists(filepath):
        return ""
    with open(filepath) as f:
        content = f.read()
    escaped = re.escape(method_name)
    pat = re.compile(
        r'((?:public|protected|private|static|\s)+'
        r'(?:\w+(?:<[^>]+>)?(?:\s*\[\])?\s+)+' + escaped +
        r'\s*\([^)]*\)\s*(?:throws\s+[^{]+)?\s*)\{', re.DOTALL)
    m = pat.search(content)
    if not m:
        return ""
    brace = content.index('{', m.end() - 1)
    depth, pos = 1, brace + 1
    while depth > 0 and pos < len(content):
        if content[pos] == '{':
            depth += 1
        elif content[pos] == '}':
            depth -= 1
        pos += 1
    body = content[m.start():pos].strip()
    lines = body.split('\n')
    if len(lines) > max_lines:
        body = '\n'.join(lines[:max_lines]) + \
               f"\n    // ... ({len(lines) - max_lines} more lines)"
    return body


def extract_snippet(filepath, method_name, before=2, after=60):
    """Extract a method and its surrounding context lines."""
    if not os.path.exists(filepath):
        return ""
    with open(filepath) as f:
        lines = f.readlines()
    escaped = re.escape(method_name)
    pat = re.compile(
        r'(?:public|protected|private|static|\s)+'
        r'(?:\w+(?:<[^>]+>)?\s+)+' + escaped + r'\s*\(')
    for i, line in enumerate(lines):
        if pat.search(line):
            return ''.join(
                lines[max(0, i - before):min(len(lines), i + after)]).strip()
    return ""


# ═════════════════════════════════════════════════════════════════════════
# CFG path info (conditions leading to / guarding each merge point)
# ═════════════════════════════════════════════════════════════════════════
CFG_PATHS = {
    # --- DataStreamer simple ---
    "hdfs::DS::run->processDatanodeOrExternalError": {
        "caller_log": "[ENTRY] DataStreamer:run()\n  IF: errorState.hasError() == true\n  CALL: processDatanodeOrExternalError() [MERGE]",
        "callee_log": "[ENTRY] DataStreamer:processDatanodeOrExternalError()\n  IF: !hasDatanodeError() && !shouldHandleExternalError() -> EXIT\n  [WARN] Error Recovery\n  IF: ++recoveryCount > 5 -> [ERROR] -> throw\n  IF: recoveryCount <= 5 -> endBlock()\n  EXIT",
    },
    "hdfs::DS::run->processDatanodeOrExternalError-INFEASIBLE": {
        "caller_log": "[ENTRY] DataStreamer:run()\n  IF: errorState.hasError()==False AND shouldHandleExternalError()==False [CALLER STATE]\n  CALL: processDatanodeOrExternalError() [INFEASIBLE]",
        "callee_log": "[ENTRY] DataStreamer:processDatanodeOrExternalError()\n  IF: !hasDatanodeError() && !shouldHandleExternalError() -> EXIT (no-op)",
    },
    "hdfs::DS::pdoe->endBlock": {
        "caller_log": "[ENTRY] DataStreamer:processDatanodeOrExternalError()\n  IF: pipelineRecoveryCount <= 5\n  CALL: endBlock() [MERGE]",
        "callee_log": "[ENTRY] DataStreamer:endBlock()\n  [INFO] Ending block {blockId}\n  EXIT",
    },
    "hdfs::DS::pdoe->endBlock-INFEASIBLE": {
        "caller_log": "[ENTRY] DataStreamer:processDatanodeOrExternalError()\n  IF: pipelineRecoveryCount==6 (exceeded) [CALLER STATE]\n  throw new IOException(\"Pipeline recovery failed\")",
        "callee_log": "[ENTRY] DataStreamer:endBlock()\n  [INFO] Ending block {blockId}\n  EXIT\n  _conflict: unreachable after throw",
    },
    "hdfs::DS::pdoe->setupPipelineForAppendOrRecovery": {
        "caller_log": "[ENTRY] DataStreamer:processDatanodeOrExternalError()\n  IF: errorState.isRestartingNode()\n  CALL: setupPipelineForAppendOrRecovery() [MERGE]",
        "callee_log": "[ENTRY] DataStreamer:setupPipelineForAppendOrRecovery()\n  EXIT",
    },
    "hdfs::DS::pdoe->initDataStreaming": {
        "caller_log": "[ENTRY] DataStreamer:processDatanodeOrExternalError()\n  IF: shouldHandleExternalError()\n  CALL: initDataStreaming() [MERGE]",
        "callee_log": "[ENTRY] DataStreamer:initDataStreaming()\n  EXIT",
    },
    "hdfs::DS::run->endBlock": {
        "caller_log": "[ENTRY] DataStreamer:run()\n  IF: one.isLastPacketInBlock() && ack confirmed\n  CALL: endBlock() [MERGE]",
        "callee_log": "[ENTRY] DataStreamer:endBlock()\n  [INFO] Ending block {blockId}\n  EXIT",
    },
    "hdfs::DS::run->closeInternal": {
        "caller_log": "[ENTRY] DataStreamer:run()\n  finally BLOCK\n  CALL: closeInternal() [MERGE, unconditional]",
        "callee_log": "[ENTRY] DataStreamer:closeInternal()\n  IF: streamerClosed -> EXIT\n  closeResponder()\n  EXIT",
    },
    "hdfs::DS::run->closeInternal-INFEASIBLE": {
        "caller_log": "[ENTRY] DataStreamer:run()\n  finally: streamerClosed==true [CALLER STATE]\n  CALL: closeInternal() [INFEASIBLE]",
        "callee_log": "[ENTRY] DataStreamer:closeInternal()\n  IF: streamerClosed -> EXIT (guard line 1)\n  _conflict: streamerClosed==true contradicts body execution",
    },
    "hdfs::DS::run->nextBlockOutputStream": {
        "caller_log": "[ENTRY] DataStreamer:run()\n  after endBlock()\n  CALL: nextBlockOutputStream() [MERGE]",
        "callee_log": "[ENTRY] DataStreamer:nextBlockOutputStream()\n  WHILE retry loop\n  EXIT",
    },
    "hdfs::DS::nbo->createBlockOutputStream": {
        "caller_log": "[ENTRY] DataStreamer:nextBlockOutputStream()\n  WHILE: retry\n  IF: !errorState.isRestartingNode()\n  CALL: createBlockOutputStream(nodes,...) [MERGE]",
        "callee_log": "[ENTRY] DataStreamer:createBlockOutputStream(List,...)\n  IF: connection fail -> setInternalError()\n  EXIT",
    },
    "hdfs::DS::nbo->createBlockOutputStream-INFEASIBLE": {
        "caller_log": "[ENTRY] DataStreamer:nextBlockOutputStream()\n  WHILE: retry\n  IF: errorState.isRestartingNode()==true [CALLER STATE] -> continue (skip)",
        "callee_log": "[ENTRY] DataStreamer:createBlockOutputStream(...)\n  _conflict: never called when isRestartingNode==true",
    },
    # --- BlockManager simple ---
    "hdfs::BM::addStoredBlock->DSI::addBlock": {
        "caller_log": "[ENTRY] BlockManager:addStoredBlock(BlockInfo, storage, ...)\n  IF: storage != null\n  CALL: storageInfo.addBlock(storedBlock, reportedBlock) [MERGE]",
        "callee_log": "[ENTRY] DatanodeStorageInfo:addBlock(BlockInfo)\n  this.blocks.add(block)\n  EXIT",
    },
    "hdfs::BM::addStoredBlock->DSI::addBlock-INFEASIBLE": {
        "caller_log": "[ENTRY] BlockManager:addStoredBlock(BlockInfo, storage==NULL, ...) [CALLER STATE]\n  _note: NPE or early return before addBlock",
        "callee_log": "[ENTRY] DatanodeStorageInfo:addBlock(BlockInfo)\n  this.blocks.add(block)\n  _conflict: NPE on null storage",
    },
    "hdfs::BM::processReport->addStoredBlock": {
        "caller_log": "[ENTRY] BlockManager:processReport(...)\n  FOR each block in report:\n  IF: !isBlockInInvalidate(blockId)\n  CALL: addStoredBlock(...) [MERGE]",
        "callee_log": "[ENTRY] BlockManager:addStoredBlock(...)\n  ...",
    },
    "hdfs::BM::processReport->addStoredBlock-INFEASIBLE": {
        "caller_log": "[ENTRY] BlockManager:processReport(...)\n  FOR each block:\n  IF: isBlockInInvalidate(blockId)==true [CALLER STATE] -> continue (skip)",
        "callee_log": "[ENTRY] BlockManager:addStoredBlock(...)\n  _conflict: skipped in processReport loop",
    },
    "hdfs::BM::removeStoredBlock->DSI::removeBlock": {
        "caller_log": "[ENTRY] BlockManager:removeStoredBlock(...)\n  CALL: storageInfo.removeBlock(block) [MERGE]",
        "callee_log": "[ENTRY] DatanodeStorageInfo:removeBlock(BlockInfo)\n  this.blocks.remove(block)\n  EXIT",
    },
    "hdfs::BM::reportDiff->DSI::removeBlock": {
        "caller_log": "[ENTRY] BlockManager:reportDiff(...)\n  FOR block in (prev - current):\n  CALL: storageInfo.removeBlock(block) [MERGE]",
        "callee_log": "[ENTRY] DatanodeStorageInfo:removeBlock(BlockInfo)\n  this.blocks.remove(block)\n  EXIT",
    },
    # --- BlockManager complex ---
    "hdfs::BM::addStoredBlock->corruptReplicasRemoveFromMap": {
        "caller_log": "[ENTRY] BlockManager:addStoredBlock(...)\n  result = storageInfo.addBlock(...)\n  IF: result==ADDED && block was in corruptReplicas\n  CALL: corruptReplicas.removeFromCorruptReplicasMap(block,node,REASON) [MERGE]",
        "callee_log": "[ENTRY] CorruptReplicasMap:removeFromCorruptReplicasMap(Block,...)\n  map.remove(block,...)\n  EXIT",
    },
    "hdfs::BM::addStoredBlock->corruptReplicasRemoveFromMap-INFEASIBLE": {
        "caller_log": "[ENTRY] BlockManager:addStoredBlock(...)\n  result==REPLACED (not ADDED) [CALLER STATE]\n  _note: corrupt map cleanup only in ADDED branch",
        "callee_log": "[ENTRY] CorruptReplicasMap:removeFromCorruptReplicasMap(...)\n  _conflict: unreachable from REPLACED branch",
    },
    "hdfs::BM::addStoredBlock->incrementSafeBlockCount": {
        "caller_log": "[ENTRY] BlockManager:addStoredBlock(...)\n  IF: result==ADDED && storedBlock.isComplete()\n  CALL: bmSafeMode.incrementSafeBlockCount(num, block) [MERGE]",
        "callee_log": "[ENTRY] BlockManagerSafeMode:incrementSafeBlockCount(int,Block)\n  IF: not in safe mode -> no-op\n  ELSE: update count\n  EXIT",
    },
    "hdfs::BM::addStoredBlock->incrementSafeBlockCount-INFEASIBLE": {
        "caller_log": "[ENTRY] BlockManager:addStoredBlock(...)\n  result==ADDED && storedBlock.isComplete()==false [CALLER STATE] -> return",
        "callee_log": "[ENTRY] BlockManagerSafeMode:incrementSafeBlockCount(...)\n  _conflict: only called for complete blocks",
    },
    "hdfs::BM::addStoredBlock->isNeededReconstruction": {
        "caller_log": "[ENTRY] BlockManager:addStoredBlock(...)\n  IF: isPopulatingReplQueues() && storedBlock.isCompleteOrCommitted()\n  CALL: isNeededReconstruction(storedBlock, num, pending) [MERGE]",
        "callee_log": "[ENTRY] BlockManager:isNeededReconstruction(Block,int,int)\n  IF: numLiveReplicas >= expected -> false\n  ELSE -> true\n  EXIT",
    },
    # --- DatanodeManager complex ---
    "hdfs::DM::registerDatanode->heartbeatManagerRegister": {
        "caller_log": "[ENTRY] DatanodeManager:registerDatanode(DatanodeRegistration)\n  IF: isIncluded(nodeReg) && topology resolved\n  CALL: heartbeatManager.register(nodeS) [MERGE]",
        "callee_log": "[ENTRY] HeartbeatManager:register(DatanodeDescriptor)\n  add to tracking\n  EXIT",
    },
    "hdfs::DM::registerDatanode->heartbeatManagerRegister-INFEASIBLE": {
        "caller_log": "[ENTRY] DatanodeManager:registerDatanode(...)\n  IF: rejectUnresolvedTopologyDN && resolve(...)==/default-rack [CALLER STATE]\n  -> throw DisallowedDatanodeException",
        "callee_log": "[ENTRY] HeartbeatManager:register(...)\n  _conflict: exception thrown before register() reachable",
    },
    "hdfs::DM::registerDatanode->updateRegInfo": {
        "caller_log": "[ENTRY] DatanodeManager:registerDatanode(...)\n  nodeS=getDatanode(uuid); nodeN=getDatanodeByXferAddr(ip,port)\n  IF: nodeS!=null && nodeS!=nodeN (replacement)\n  CALL: nodeS.updateRegInfo(nodeReg) [MERGE]",
        "callee_log": "[ENTRY] DatanodeDescriptor:updateRegInfo(DatanodeRegistration)\n  update ip/port/version\n  EXIT",
    },
    "hdfs::DM::registerDatanode->addDatanode": {
        "caller_log": "[ENTRY] DatanodeManager:registerDatanode(...)\n  IF: nodeS==null (no existing node with same UUID)\n  CALL: heartbeatManager.addDatanode(nodeDescr) [MERGE]",
        "callee_log": "[ENTRY] HeartbeatManager:addDatanode(DatanodeDescriptor)\n  insert new node\n  EXIT",
    },
}


# ═════════════════════════════════════════════════════════════════════════
# Merge-point definitions (ground truth)
# ═════════════════════════════════════════════════════════════════════════

# ---------- Original 27 (simple=18, complex=9) ----------
_SIMPLE_ORIG = [
    {"mp_id":"hdfs::DS::run->processDatanodeOrExternalError","caller":"DataStreamer:run()","callee":"DataStreamer:processDatanodeOrExternalError()","gt":"valid","rationale":"run() calls processDatanodeOrExternalError when errorState.hasError() is true after pipeline failure."},
    {"mp_id":"hdfs::DS::run->processDatanodeOrExternalError-INFEASIBLE","caller":"DataStreamer:run()","callee":"DataStreamer:processDatanodeOrExternalError()","gt":"infeasible","infeasible_reason":"hasError()==false && shouldHandleExternalError()==false — no error condition exists to trigger this call."},
    {"mp_id":"hdfs::DS::pdoe->endBlock","caller":"DataStreamer:processDatanodeOrExternalError()","callee":"DataStreamer:endBlock()","gt":"valid","rationale":"After pipeline recovery (pipelineRecoveryCount<=5), calls endBlock to finalize current block."},
    {"mp_id":"hdfs::DS::pdoe->endBlock-INFEASIBLE","caller":"DataStreamer:processDatanodeOrExternalError()","callee":"DataStreamer:endBlock()","gt":"infeasible","infeasible_reason":"pipelineRecoveryCount>5 — IOException thrown before reaching endBlock()."},
    {"mp_id":"hdfs::DS::pdoe->setupPipelineForAppendOrRecovery","caller":"DataStreamer:processDatanodeOrExternalError()","callee":"DataStreamer:setupPipelineForAppendOrRecovery()","gt":"valid","rationale":"Called when error is recoverable (errorState.isRestartingNode())."},
    {"mp_id":"hdfs::DS::pdoe->initDataStreaming","caller":"DataStreamer:processDatanodeOrExternalError()","callee":"DataStreamer:initDataStreaming()","gt":"valid","rationale":"After handling external error (shouldHandleExternalError()==true), re-initializes stream."},
    {"mp_id":"hdfs::DS::run->endBlock","caller":"DataStreamer:run()","callee":"DataStreamer:endBlock()","gt":"valid","rationale":"Called when final ACK received; stage transitions DATA_STREAMING→PIPELINE_CLOSE."},
    {"mp_id":"hdfs::DS::run->closeInternal","caller":"DataStreamer:run()","callee":"DataStreamer:closeInternal()","gt":"valid","rationale":"Unconditionally reachable in finally block."},
    {"mp_id":"hdfs::DS::run->closeInternal-INFEASIBLE","caller":"DataStreamer:run()","callee":"DataStreamer:closeInternal()","gt":"infeasible","infeasible_reason":"streamerClosed==true but callee path continues past guard: closeInternal checks if(streamerClosed) return; first."},
    {"mp_id":"hdfs::DS::run->nextBlockOutputStream","caller":"DataStreamer:run()","callee":"DataStreamer:nextBlockOutputStream()","gt":"valid","rationale":"After endBlock(), creates output stream for next block."},
    {"mp_id":"hdfs::DS::nbo->createBlockOutputStream","caller":"DataStreamer:nextBlockOutputStream()","callee":"DataStreamer:createBlockOutputStream(java.util.List,int,long)","gt":"valid","rationale":"nextBlockOutputStream calls createBlockOutputStream in retry loop."},
    {"mp_id":"hdfs::DS::nbo->createBlockOutputStream-INFEASIBLE","caller":"DataStreamer:nextBlockOutputStream()","callee":"DataStreamer:createBlockOutputStream(java.util.List,int,long)","gt":"infeasible","infeasible_reason":"errorState.isRestartingNode()==true — loop continues without calling createBlockOutputStream."},
    {"mp_id":"hdfs::BM::addStoredBlock->DSI::addBlock","caller":"BlockManager:addStoredBlock(BlockInfo,DatanodeStorageInfo,DatanodeDescriptor,boolean)","callee":"DatanodeStorageInfo:addBlock(BlockInfo)","gt":"valid","rationale":"Registers block on DatanodeStorageInfo after block report."},
    {"mp_id":"hdfs::BM::addStoredBlock->DSI::addBlock-INFEASIBLE","caller":"BlockManager:addStoredBlock(...)","callee":"DatanodeStorageInfo:addBlock(...)","gt":"infeasible","infeasible_reason":"storageInfo==null — caller guards with null check."},
    {"mp_id":"hdfs::BM::processReport->addStoredBlock","caller":"BlockManager:processReport(DatanodeDescriptor,DatanodeStorageInfo,StorageBlockReport[],boolean)","callee":"BlockManager:addStoredBlock(BlockInfo,DatanodeStorageInfo,DatanodeDescriptor,boolean)","gt":"valid","rationale":"processReport iterates storage report blocks; calls addStoredBlock for each untracked block."},
    {"mp_id":"hdfs::BM::processReport->addStoredBlock-INFEASIBLE","caller":"BlockManager:processReport(...)","callee":"BlockManager:addStoredBlock(...)","gt":"infeasible","infeasible_reason":"blockManager.isBlockInInvalidate(blockId)==true — blocks queued for invalidation are skipped."},
    {"mp_id":"hdfs::BM::removeStoredBlock->DSI::removeBlock","caller":"BlockManager:removeStoredBlock(BlockInfo,DatanodeDescriptor)","callee":"DatanodeStorageInfo:removeBlock(BlockInfo)","gt":"valid","rationale":"Unregisters block when datanode reports removal/corruption."},
    {"mp_id":"hdfs::BM::reportDiff->DSI::removeBlock","caller":"BlockManager:reportDiff(DatanodeStorageInfo,BlockListAsLongs,BlockListAsLongs,int)","callee":"DatanodeStorageInfo:removeBlock(BlockInfo)","gt":"valid","rationale":"Removes blocks that appear in previous report but not current."},
]

_COMPLEX_ORIG = [
    {"mp_id":"hdfs::BM::addStoredBlock->corruptReplicasRemoveFromMap","caller":"BlockManager:addStoredBlock(BlockInfo,DatanodeStorageInfo,DatanodeDescriptor,boolean)","callee":"CorruptReplicasMap:removeFromCorruptReplicasMap(Block,DatanodeDescriptor,Reason)","gt":"valid","rationale":"When result==ADDED and storedBlock was previously corrupt, removes from corrupt map."},
    {"mp_id":"hdfs::BM::addStoredBlock->corruptReplicasRemoveFromMap-INFEASIBLE","caller":"BlockManager:addStoredBlock(...)","callee":"CorruptReplicasMap:removeFromCorruptReplicasMap(...)","gt":"infeasible","infeasible_reason":"result==REPLACED (not ADDED) — removeFromCorruptReplicasMap only in ADDED branch."},
    {"mp_id":"hdfs::BM::addStoredBlock->incrementSafeBlockCount","caller":"BlockManager:addStoredBlock(BlockInfo,DatanodeStorageInfo,DatanodeDescriptor,boolean)","callee":"BlockManagerSafeMode:incrementSafeBlockCount(int,Block)","gt":"valid","rationale":"After ADDED result, if block is complete and safe mode is active."},
    {"mp_id":"hdfs::BM::addStoredBlock->incrementSafeBlockCount-INFEASIBLE","caller":"BlockManager:addStoredBlock(...)","callee":"BlockManagerSafeMode:incrementSafeBlockCount(...)","gt":"infeasible","infeasible_reason":"storedBlock.isComplete()==false — guarded by isComplete() && result==ADDED."},
    {"mp_id":"hdfs::BM::addStoredBlock->isNeededReconstruction","caller":"BlockManager:addStoredBlock(BlockInfo,DatanodeStorageInfo,DatanodeDescriptor,boolean)","callee":"BlockManager:isNeededReconstruction(Block,int,int)","gt":"valid","rationale":"After redundancy computed, checks isNeededReconstruction for reconstruction queue."},
    {"mp_id":"hdfs::DM::registerDatanode->heartbeatManagerRegister","caller":"DatanodeManager:registerDatanode(DatanodeRegistration)","callee":"HeartbeatManager:register(DatanodeDescriptor)","gt":"valid","rationale":"After resolving network location, registers node with heartbeatManager."},
    {"mp_id":"hdfs::DM::registerDatanode->heartbeatManagerRegister-INFEASIBLE","caller":"DatanodeManager:registerDatanode(...)","callee":"HeartbeatManager:register(...)","gt":"infeasible","infeasible_reason":"rejectUnresolvedTopologyDN==true && resolve returns /default-rack — DisallowedDatanodeException thrown."},
    {"mp_id":"hdfs::DM::registerDatanode->updateRegInfo","caller":"DatanodeManager:registerDatanode(DatanodeRegistration)","callee":"DatanodeDescriptor:updateRegInfo(DatanodeRegistration)","gt":"valid","rationale":"Replacement scenario: same UUID but different IP/port."},
    {"mp_id":"hdfs::DM::registerDatanode->addDatanode","caller":"DatanodeManager:registerDatanode(DatanodeRegistration)","callee":"HeartbeatManager:addDatanode(DatanodeDescriptor)","gt":"valid","rationale":"Genuinely new node (no existing node with same UUID)."},
]

# ---------- Extended 13 (simple=10, complex=3) ----------
_SIMPLE_EXT = [
    {"mp_id":"hdfs::DS::writeTo->createBlockOutputStream","system":"hdfs","stratum":"simple","caller":"DataStreamer:writeTo(DataOutputStream)","callee":"DataStreamer:createBlockOutputStream(List,int,long)","gt":"valid","rationale":"writeTo triggers pipeline re-creation on write failure.","caller_log":"[ENTRY] DataStreamer:writeTo()\n  IF: write fails (IOException)\n  CALL: createBlockOutputStream(nodes,...) [MERGE]","callee_log":"[ENTRY] DataStreamer:createBlockOutputStream(List,int,long)\n  connect to datanodes\n  IF: fail -> setInternalError()\n  EXIT","caller_code":"","callee_code":"","gt_source":"manual","gt_detail":{}},
    {"mp_id":"hdfs::DS::run->backOffIfNecessary","system":"hdfs","stratum":"simple","caller":"DataStreamer:run()","callee":"DataStreamer:backOffIfNecessary()","gt":"valid","rationale":"Between retry attempts, run() calls backOffIfNecessary for exponential backoff.","caller_log":"[ENTRY] DataStreamer:run()\n  IF: errorState.hasError() && !errorState.isRestartingNode()\n  CALL: backOffIfNecessary() [MERGE]","callee_log":"[ENTRY] DataStreamer:backOffIfNecessary()\n  sleep for retry backoff\n  EXIT","caller_code":"","callee_code":"","gt_source":"manual","gt_detail":{}},
    {"mp_id":"hdfs::DS::run->waitForAllAcks","system":"hdfs","stratum":"simple","caller":"DataStreamer:run()","callee":"DataStreamer:waitForAllAcks()","gt":"valid","rationale":"After sending the last packet, blocks on waitForAllAcks.","caller_log":"[ENTRY] DataStreamer:run()\n  IF: one.isLastPacketInBlock() && packet sent\n  CALL: waitForAllAcks() [MERGE]","callee_log":"[ENTRY] DataStreamer:waitForAllAcks()\n  wait until all acks received or timeout\n  EXIT","caller_code":"","callee_code":"","gt_source":"manual","gt_detail":{}},
    {"mp_id":"hdfs::DS::createBlockOutputStream->checkRestartingNode","system":"hdfs","stratum":"simple","caller":"DataStreamer:createBlockOutputStream(List,int,long)","callee":"DataStreamer$ErrorState:checkRestartingNode()","gt":"valid","rationale":"Checks restart state at entry; if restarting, returns without creating stream.","caller_log":"[ENTRY] DataStreamer:createBlockOutputStream(...)\n  IF: errorState.checkRestartingNode() == true\n  CALL: checkRestartingNode() [MERGE]","callee_log":"[ENTRY] ErrorState:checkRestartingNode()\n  IF: isRestartingNode() -> reset + return true\n  ELSE: return false\n  EXIT","caller_code":"","callee_code":"","gt_source":"manual","gt_detail":{}},
    {"mp_id":"hdfs::DS::cbo->getXferAddr","system":"hdfs","stratum":"simple","caller":"DataStreamer:createBlockOutputStream(List,int,long)","callee":"DatanodeInfo:getXferAddr()","gt":"valid","rationale":"Reads datanode transfer addresses to establish socket connections.","caller_log":"[ENTRY] DataStreamer:createBlockOutputStream(...)\n  FOR each node in pipeline:\n  CALL: node.getXferAddr() [MERGE]","callee_log":"[ENTRY] DatanodeInfo:getXferAddr()\n  return transfer address string\n  EXIT","caller_code":"","callee_code":"","gt_source":"manual","gt_detail":{}},
    {"mp_id":"hdfs::DS::pdoe->initDataStreaming-INFEASIBLE","system":"hdfs","stratum":"simple","caller":"DataStreamer:processDatanodeOrExternalError()","callee":"DataStreamer:initDataStreaming()","gt":"infeasible","infeasible_reason":"shouldHandleExternalError()==false","caller_log":"[ENTRY] DataStreamer:processDatanodeOrExternalError()\n  IF: shouldHandleExternalError()==false [STATE]\n  CALL: initDataStreaming() [INFEASIBLE]","callee_log":"[ENTRY] DataStreamer:initDataStreaming()\n  EXIT\n  _conflict: unreachable from non-external-error path","caller_code":"","callee_code":"","gt_source":"manual","gt_detail":{}},
    {"mp_id":"hdfs::DS::run->endBlock-INFEASIBLE","system":"hdfs","stratum":"simple","caller":"DataStreamer:run()","callee":"DataStreamer:endBlock()","gt":"infeasible","infeasible_reason":"stage already PIPELINE_CLOSE; second endBlock call unreachable","caller_log":"[ENTRY] DataStreamer:run()\n  stage == PIPELINE_CLOSE [STATE]\n  CALL: endBlock() [INFEASIBLE]","callee_log":"[ENTRY] DataStreamer:endBlock()\n  [INFO] Ending block\n  _conflict: duplicate endBlock in same loop","caller_code":"","callee_code":"","gt_source":"manual","gt_detail":{}},
    {"mp_id":"hdfs::BM::removeStoredBlock->DSI::removeBlock-INFEASIBLE","system":"hdfs","stratum":"simple","caller":"BlockManager:removeStoredBlock(BlockInfo,DatanodeDescriptor)","callee":"DatanodeStorageInfo:removeBlock(BlockInfo)","gt":"infeasible","infeasible_reason":"findStorageInfo returns null — storageInfo already removed","caller_log":"[ENTRY] BlockManager:removeStoredBlock(...)\n  findStorageInfo(node) -> null [STATE]\n  CALL: storageInfo.removeBlock(block) [INFEASIBLE]","callee_log":"[ENTRY] DatanodeStorageInfo:removeBlock(BlockInfo)\n  _conflict: NPE on null storage","caller_code":"","callee_code":"","gt_source":"manual","gt_detail":{}},
    {"mp_id":"hdfs::DS::run->processDatanodeOrExternalError-INFEASIBLE-2","system":"hdfs","stratum":"simple","caller":"DataStreamer:run()","callee":"DataStreamer:processDatanodeOrExternalError()","gt":"infeasible","infeasible_reason":"stage==PIPELINE_CLOSE; error recovery only applies during DATA_STREAMING","caller_log":"[ENTRY] DataStreamer:run()\n  stage==PIPELINE_CLOSE [STATE]\n  CALL: processDatanodeOrExternalError() [INFEASIBLE]","callee_log":"[ENTRY] DataStreamer:processDatanodeOrExternalError()\n  _conflict: error recovery meaningless in CLOSE state","caller_code":"","callee_code":"","gt_source":"manual","gt_detail":{}},
    {"mp_id":"hdfs::BM::processReport->invalidateBlocks-INFEASIBLE","system":"hdfs","stratum":"simple","caller":"BlockManager:processReport(...)","callee":"BlockManager:invalidateBlocks(int)","gt":"infeasible","infeasible_reason":"invalidateBlocks list is empty; method skipped","caller_log":"[ENTRY] BlockManager:processReport(...)\n  invalidateBlocks is empty [STATE]\n  CALL: invalidateBlocks(...) [INFEASIBLE]","callee_log":"[ENTRY] BlockManager:invalidateBlocks(int)\n  _conflict: never called with empty list","caller_code":"","callee_code":"","gt_source":"manual","gt_detail":{}},
]

_COMPLEX_EXT = [
    {"mp_id":"hdfs::BM::addStoredBlock->countNodes","system":"hdfs","stratum":"complex","caller":"BlockManager:addStoredBlock(BlockInfo,DatanodeStorageInfo,DatanodeDescriptor,boolean)","callee":"BlockManager:countNodes(BlockInfo)","gt":"valid","rationale":"Counts live/decommissioning/maintenance replica counts for safe mode and redundancy decisions.","caller_log":"[ENTRY] BlockManager:addStoredBlock(...)\n  IF: block added successfully\n  CALL: countNodes(storedBlock) [MERGE]","callee_log":"[ENTRY] BlockManager:countNodes(BlockInfo)\n  count live/decommissioning/corrupt replicas per storage\n  return NumberReplicas\n  EXIT","caller_code":"","callee_code":"","gt_source":"manual","gt_detail":{}},
    {"mp_id":"hdfs::BM::processReport->removeFromInvalidates","system":"hdfs","stratum":"complex","caller":"BlockManager:processReport(...)","callee":"InvalidateBlocks:remove(DatanodeDescriptor,Block)","gt":"valid","rationale":"Blocks pending invalidation are removed from the queue after processing.","caller_log":"[ENTRY] BlockManager:processReport(...)\n  FOR each block in diff:\n  CALL: invalidateBlocks.remove(node, block) [MERGE]","callee_log":"[ENTRY] InvalidateBlocks:remove(DatanodeDescriptor,Block)\n  remove from queue\n  EXIT","caller_code":"","callee_code":"","gt_source":"manual","gt_detail":{}},
    {"mp_id":"hdfs::DM::registerDatanode->setNetworkLocation","system":"hdfs","stratum":"complex","caller":"DatanodeManager:registerDatanode(DatanodeRegistration)","callee":"DatanodeDescriptor:setNetworkLocation(String)","gt":"valid","rationale":"Resolves and sets rack location via DNS-to-switch mapping.","caller_log":"[ENTRY] DatanodeManager:registerDatanode(...)\n  loc = resolveNetworkLocation(nodeS)\n  CALL: nodeS.setNetworkLocation(loc) [MERGE]","callee_log":"[ENTRY] DatanodeDescriptor:setNetworkLocation(String)\n  set rack location for topology-aware scheduling\n  EXIT","caller_code":"","callee_code":"","gt_source":"manual","gt_detail":{}},
]


# ═════════════════════════════════════════════════════════════════════════
# Build dataset
# ═════════════════════════════════════════════════════════════════════════
def build(repo_root):
    """Assemble the full 40-merge-point dataset."""
    # Source-file paths
    hdfs_client = os.path.join(repo_root, "hadoop/hadoop-hdfs-project/"
                               "hadoop-hdfs-client/src/main/java/org/apache/"
                               "hadoop/hdfs")
    hdfs_bm = os.path.join(repo_root, "hadoop/hadoop-hdfs-project/hadoop-hdfs/"
                            "src/main/java/org/apache/hadoop/hdfs/server/"
                            "blockmanagement")
    FILE_MAP = {
        "DataStreamer": os.path.join(hdfs_client, "DataStreamer.java"),
        "BlockManager": os.path.join(hdfs_bm, "BlockManager.java"),
        "DatanodeStorageInfo": os.path.join(hdfs_bm, "DatanodeStorageInfo.java"),
        "DatanodeManager": os.path.join(hdfs_bm, "DatanodeManager.java"),
        "CorruptReplicasMap": os.path.join(hdfs_bm, "CorruptReplicasMap.java"),
        "BlockManagerSafeMode": os.path.join(hdfs_bm, "BlockManagerSafeMode.java"),
        "HeartbeatManager": os.path.join(hdfs_bm, "HeartbeatManager.java"),
        "DatanodeDescriptor": os.path.join(hdfs_bm, "DatanodeDescriptor.java"),
    }

    _COMPLEX_IDS = {"addStoredBlock->corrupt", "addStoredBlock->increment",
                    "addStoredBlock->isNeeded", "addStoredBlock->countNodes",
                    "registerDatanode", "processReport->removeFrom"}

    dataset = []
    for mp in _SIMPLE_ORIG + _COMPLEX_ORIG + _SIMPLE_EXT + _COMPLEX_EXT:
        entry = dict(mp)
        entry.setdefault("system", "hdfs")
        entry.setdefault("gt_source", "manual")
        entry.setdefault("gt_detail", {"rationale": mp.get("rationale", "")})
        entry.setdefault("stratum",
            "complex" if any(k in mp["mp_id"] for k in _COMPLEX_IDS)
            else "simple")

        # Extract source code for original 27 (extended already have empty code)
        if "caller_code" not in entry:
            caller_cls = mp["caller"].split(":")[0].split(".")[-1]
            callee_cls = mp["callee"].split(":")[0].split(".")[-1]
            caller_mtd = mp["caller"].split(":")[-1].split("(")[0]
            callee_mtd = mp["callee"].split(":")[-1].split("(")[0]
            caller_file = FILE_MAP.get(caller_cls, "")
            callee_file = FILE_MAP.get(callee_cls, "")
            entry["caller_code"] = (extract_snippet(caller_file, caller_mtd)
                                    or extract_method(caller_file, caller_mtd, 40))
            entry["callee_code"] = (extract_snippet(callee_file, callee_mtd)
                                    or extract_method(callee_file, callee_mtd, 40))
            # Do not prefix caller_code with "// INFEASIBLE: ...": that
            # string is concatenated into the LLM prompt by run_one() and
            # leaks the ground-truth label.  The reason stays in
            # infeasible_reason / gt_detail, which are not sent to the model.

        # Add CFG path info
        cfg = CFG_PATHS.get(mp["mp_id"], {})
        entry.setdefault("caller_log", cfg.get("caller_log",
            f"// CFG: caller calls callee"))
        entry.setdefault("callee_log", cfg.get("callee_log",
            f"// CFG: callee"))

        dataset.append(entry)

    return dataset


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=os.path.dirname(HERE),
                    help="Path to AnomalyGen-main repository root")
    args = ap.parse_args()

    dataset = build(args.repo)

    out_path = os.path.join(EVAL_DATA, "feasibility_manual.jsonl")
    with open(out_path, "w", encoding="utf-8") as f:
        for item in dataset:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    simple = [d for d in dataset if d["stratum"] == "simple"]
    complex_ = [d for d in dataset if d["stratum"] == "complex"]
    valid = [d for d in dataset if d["gt"] == "valid"]
    infeasible = [d for d in dataset if d["gt"] == "infeasible"]

    print(f"Generated {len(dataset)} merge points -> {out_path}")
    print(f"  Simple:     {len(simple)} "
          f"({sum(1 for d in simple if d['gt']=='valid')} valid + "
          f"{sum(1 for d in simple if d['gt']=='infeasible')} infeasible)")
    print(f"  Complex:    {len(complex_)} "
          f"({sum(1 for d in complex_ if d['gt']=='valid')} valid + "
          f"{sum(1 for d in complex_ if d['gt']=='infeasible')} infeasible)")
    print(f"  Total:      {len(valid)} feasible + {len(infeasible)} infeasible")


if __name__ == "__main__":
    main()
