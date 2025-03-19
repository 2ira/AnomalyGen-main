package com.example;

import com.github.javaparser.resolution.types.ResolvedType;
import com.github.javaparser.StaticJavaParser;
import com.github.javaparser.ast.CompilationUnit;
import com.github.javaparser.ast.body.MethodDeclaration;
import com.github.javaparser.ast.expr.*;
import com.github.javaparser.ast.stmt.*;
import com.github.javaparser.ast.visitor.VoidVisitorAdapter;
import com.github.javaparser.ast.expr.VariableDeclarationExpr;
import com.github.javaparser.ast.body.VariableDeclarator;
import py4j.GatewayServer;
import com.github.javaparser.ast.NodeList;
import java.util.stream.Stream;
import java.util.*;
import java.util.stream.Collectors;

class CFGNode {
    String label;
    List<CFGNode> successors = new ArrayList<>();

    CFGNode(String label) {
        this.label = label;
    }

    void addSuccessor(CFGNode node) {
        successors.add(node);
    }

    @Override
    public String toString() {
        return label;
    }
}

public class JavaParserServer {

    private static final int MAX_RECURSION_DEPTH = 5;
    private static final int MAX_PATH_DEPTH = 20;

    // 用于处理循环中 break/continue（无标签）的循环上下文栈
    private Deque<CFGNode> loopHeaderStack = new ArrayDeque<>();
    // 用于记录带标签的 break/continue 目标
    private Map<String, CFGNode> labeledBreakMap = new HashMap<>();
    private Map<String, CFGNode> labeledContinueMap = new HashMap<>();

    // ====================== 控制流图核心逻辑 ======================
    public CFGNode buildCFG(String code) {
        CompilationUnit cu = StaticJavaParser.parse(code);
        MethodDeclaration method = cu.findFirst(MethodDeclaration.class)
                .orElseThrow(() -> new IllegalArgumentException("No method found"));
        CFGNode entry = new CFGNode("ENTRY");
        CFGNode exit = new CFGNode("EXIT");

        List<CFGNode> currentFlow = new ArrayList<>();
        currentFlow.add(entry);
        processStatement(method.getBody().orElse(null), currentFlow, exit);
        linkToExit(currentFlow, exit);
        return entry;
    }

    private void processStatement(Statement stmt, List<CFGNode> incoming, CFGNode exit) {
        if (stmt == null) return;
        if (stmt instanceof BlockStmt) {
            handleBlock((BlockStmt) stmt, incoming, exit);
        } else if (stmt instanceof IfStmt) {
            handleIf((IfStmt) stmt, incoming, exit);
        } else if (stmt instanceof ForStmt) {
            handleFor((ForStmt) stmt, incoming, exit);
        } else if (stmt instanceof WhileStmt) {
            handleWhile((WhileStmt) stmt, incoming, exit);
        } else if (stmt instanceof DoStmt) {
            handleDoWhile((DoStmt) stmt, incoming, exit);
        } else if (stmt instanceof SwitchStmt) {
            handleSwitch((SwitchStmt) stmt, incoming, exit);
        } else if (stmt instanceof TryStmt) {
            handleTryCatch((TryStmt) stmt, incoming, exit);
        } else if (stmt instanceof ExpressionStmt) {
            handleExpressionStmt((ExpressionStmt) stmt, incoming, exit, false, null);
        } else if (stmt instanceof SynchronizedStmt) {
            handleSynchronized((SynchronizedStmt) stmt, incoming, exit);
        } else if (stmt instanceof LabeledStmt) {
            handleLabeled((LabeledStmt) stmt, incoming, exit);
        } else if (stmt instanceof ForEachStmt) {
            handleForEach((ForEachStmt) stmt, incoming, exit);
        } else if (stmt instanceof ReturnStmt) {
            handleReturn((ReturnStmt) stmt, incoming, exit);
        } else if (stmt instanceof BreakStmt) {
            handleBreak((BreakStmt) stmt, incoming, exit);
        } else if (stmt instanceof ContinueStmt) {
            handleContinue((ContinueStmt) stmt, incoming, exit);
        } else if (stmt instanceof ThrowStmt) {
            handleThrow((ThrowStmt) stmt, incoming, exit);
        } else if (stmt instanceof ExpressionStmt
                && ((ExpressionStmt) stmt).getExpression() instanceof VariableDeclarationExpr) {
            handleVariableDeclaration(
                (VariableDeclarationExpr) ((ExpressionStmt) stmt).getExpression(), 
                incoming, 
                exit
            );
        } else if (stmt instanceof EmptyStmt) {
            // 空语句不创建节点
        } else {
            System.out.println("Unprocessed statement: " + stmt.getClass().getSimpleName());
        }
    }

    // ====================== 具体语句处理方法 ======================
    private void handleBlock(BlockStmt block, List<CFGNode> incoming, CFGNode exit) {
        List<CFGNode> current = new ArrayList<>(incoming);
        for (Statement stmt : block.getStatements()) {
            processStatement(stmt, current, exit);
            current = getExitNodes(current);
        }
        incoming.clear();
        incoming.addAll(current);
    }

    // 改进后的 if 处理：同时创建 IF_TRUE 与 IF_FALSE 分支
    private void handleIf(IfStmt ifStmt, List<CFGNode> incoming, CFGNode exit) {
        CFGNode trueNode = createNode("IF_TRUE: " + ifStmt.getCondition());
        CFGNode falseNode = createNode("IF_FALSE: " + ifStmt.getCondition());
        // 将入口同时分到两个分支
        link(incoming, trueNode);
        link(incoming, falseNode);
        List<CFGNode> thenExit = processBranch(ifStmt.getThenStmt(), trueNode, exit);
        List<CFGNode> elseExit = new ArrayList<>();
        if (ifStmt.getElseStmt().isPresent()) {
            elseExit.addAll(processBranch(ifStmt.getElseStmt().get(), falseNode, exit));
        } else {
            elseExit.add(falseNode);
        }
        incoming.clear();
        incoming.addAll(thenExit);
        incoming.addAll(elseExit);
    }

    private void handleFor(ForStmt forStmt, List<CFGNode> incoming, CFGNode exit) {
        CFGNode initNode = createNode("FOR_INIT");
        link(incoming, initNode);
        for (Expression expr : forStmt.getInitialization()) {
            analyzeExpression(expr, new ArrayList<>(Collections.singletonList(initNode)), 0);
        }
        String cond = forStmt.getCompare().map(Expression::toString).orElse("TRUE");
        CFGNode condNode = createNode("FOR_COND: " + cond);
        initNode.addSuccessor(condNode);

        loopHeaderStack.push(condNode);

        List<CFGNode> bodyEntries = new ArrayList<>();
        bodyEntries.add(condNode);
        processStatement(forStmt.getBody(), bodyEntries, exit);

        CFGNode updateNode = createNode("FOR_UPDATE");
        for (Expression expr : forStmt.getUpdate()) {
            analyzeExpression(expr, new ArrayList<>(Collections.singletonList(updateNode)), 0);
        }
        link(getExitNodes(bodyEntries), updateNode);
        updateNode.addSuccessor(condNode);

        CFGNode forExit = createNode("FOR_EXIT");
        condNode.addSuccessor(forExit);

        loopHeaderStack.pop();

        incoming.clear();
        incoming.add(forExit);
    }

    private void handleWhile(WhileStmt stmt, List<CFGNode> incoming, CFGNode exit) {
        CFGNode whileNode = createNode("WHILE: " + stmt.getCondition());
        link(incoming, whileNode);

        CFGNode condNode = createNode("WHILE_COND: " + stmt.getCondition());
        whileNode.addSuccessor(condNode);

        loopHeaderStack.push(condNode);

        List<CFGNode> bodyEntries = new ArrayList<>();
        bodyEntries.add(condNode);
        processStatement(stmt.getBody(), bodyEntries, exit);

        link(getExitNodes(bodyEntries), condNode);

        CFGNode exitNode = createNode("WHILE_EXIT");
        condNode.addSuccessor(exitNode);

        loopHeaderStack.pop();

        incoming.clear();
        incoming.add(exitNode);
    }

    private void handleDoWhile(DoStmt stmt, List<CFGNode> incoming, CFGNode exit) {
        CFGNode doNode = createNode("DO_WHILE");
        link(incoming, doNode);

        List<CFGNode> bodyEntries = new ArrayList<>();
        bodyEntries.add(doNode);
        processStatement(stmt.getBody(), bodyEntries, exit);

        CFGNode condNode = createNode("DO_COND: " + stmt.getCondition());
        link(getExitNodes(bodyEntries), condNode);
        condNode.addSuccessor(doNode);

        CFGNode exitNode = createNode("DO_EXIT");
        condNode.addSuccessor(exitNode);
        incoming.clear();
        incoming.add(exitNode);
    }

    private void handleSwitch(SwitchStmt switchStmt, List<CFGNode> incoming, CFGNode exit) {
        CFGNode switchNode = createNode("SWITCH: " + switchStmt.getSelector());
        link(incoming, switchNode);

        List<CFGNode> caseExits = new ArrayList<>();
        for (SwitchEntry entry : switchStmt.getEntries()) {
            CFGNode caseNode = createNode("CASE: " + entry.getLabels());
            switchNode.addSuccessor(caseNode);

            List<CFGNode> caseEntries = new ArrayList<>();
            caseEntries.add(caseNode);
            for (Statement stmt : entry.getStatements()) {
                processStatement(stmt, caseEntries, exit);
            }
            caseExits.addAll(getExitNodes(caseEntries));
        }
        incoming.clear();
        incoming.addAll(caseExits);
    }

    private void handleForEach(ForEachStmt stmt, List<CFGNode> incoming, CFGNode exit) {
        CFGNode forEachNode = createNode("FOREACH: " + stmt.getIterable());
        link(incoming, forEachNode);

        List<CFGNode> bodyEntries = new ArrayList<>();
        bodyEntries.add(forEachNode);
        processStatement(stmt.getBody(), bodyEntries, exit);

        link(getExitNodes(bodyEntries), forEachNode);

        CFGNode exitNode = createNode("FOREACH_EXIT");
        forEachNode.addSuccessor(exitNode);
        incoming.clear();
        incoming.add(exitNode);
    }

    private void handleSynchronized(SynchronizedStmt stmt, List<CFGNode> incoming, CFGNode exit) {
        CFGNode syncNode = createNode("SYNC: " + stmt.getExpression());
        link(incoming, syncNode);
        processStatement(stmt.getBody(), new ArrayList<>(Collections.singletonList(syncNode)), exit);
        incoming.clear();
        incoming.addAll(getExitNodes(new ArrayList<>(Collections.singletonList(syncNode))));
    }

    // -------------------- try/catch/finally 处理 --------------------
    private void handleTryCatch(TryStmt stmt, List<CFGNode> incoming, CFGNode exit) {
        CFGNode tryNode = createNode("TRY");
        link(incoming, tryNode);

        List<CFGNode> tryEntries = new ArrayList<>();
        tryEntries.add(tryNode);
        List<CFGNode> currentCatchIncoming = new ArrayList<>();
        for (Statement s : stmt.getTryBlock().getStatements()) {
            handleStatement(s, tryEntries, exit, true, currentCatchIncoming);
        }
        List<CFGNode> normalExits = getExitNodes(tryEntries);
        List<CFGNode> exceptionExits = getExitNodes(currentCatchIncoming);
        // 如果 try 块没有产生异常边，则创建一个默认异常出口
        if (exceptionExits.isEmpty()) {
            CFGNode defaultEx = createNode("EXCEPTION_DEFAULT");
            exceptionExits.add(defaultEx);
        }

        List<CFGNode> catchExits = new ArrayList<>();
        for (CatchClause catchClause : stmt.getCatchClauses()) {
            CFGNode catchEntry = createNode("CATCH: " + catchClause.getParameter().getType() 
                    + " " + catchClause.getParameter().getName());
            for (CFGNode exNode : exceptionExits) {
                exNode.addSuccessor(catchEntry);
            }
            List<CFGNode> catchEntries = new ArrayList<>();
            catchEntries.add(catchEntry);
            for (Statement s : catchClause.getBody().getStatements()) {
                handleStatement(s, catchEntries, exit, false, null);
            }
            catchExits.addAll(getExitNodes(catchEntries));
        }
        List<CFGNode> totalExits = new ArrayList<>();
        totalExits.addAll(normalExits);
        totalExits.addAll(catchExits);

        if (stmt.getFinallyBlock().isPresent()) {
            List<CFGNode> finallyEntries = new ArrayList<>(totalExits);
            for (Statement s : stmt.getFinallyBlock().get().getStatements()) {
                handleStatement(s, finallyEntries, exit, false, null);
            }
            incoming.clear();
            incoming.addAll(getExitNodes(finallyEntries));
        } else {
            incoming.clear();
            incoming.addAll(totalExits);
        }
    }

    // -------------------- 变量声明 --------------------
    private void handleVariableDeclaration(VariableDeclarationExpr expr, 
                                        List<CFGNode> incoming, 
                                        CFGNode exit) {
        List<CFGNode> current = new ArrayList<>(incoming);
        for (VariableDeclarator var : expr.getVariables()) {
            if (var.getInitializer().isPresent()) {
                Expression init = var.getInitializer().get();
                List<CFGNode> tempList = new ArrayList<>(current);
                analyzeExpression(init, tempList, 0);
                List<MethodCallExpr> subCalls = init.findAll(MethodCallExpr.class);
                for (MethodCallExpr subCall : subCalls) {
                    List<CFGNode> callNodes = new ArrayList<>(tempList);
                    handleMethodCall(subCall, callNodes, false, null);
                    tempList = new ArrayList<>(callNodes);
                }
                current = new ArrayList<>(tempList);
            }
        }
        incoming.clear();
        incoming.addAll(current);
    }

    private boolean containsMethodCall(Expression expr) {
        MethodCallDetector detector = new MethodCallDetector();
        expr.accept(detector, null);
        return detector.hasCall();
    }

    private static class MethodCallDetector extends VoidVisitorAdapter<Void> {
        private boolean hasCall = false;
        @Override
        public void visit(MethodCallExpr n, Void arg) {
            hasCall = true;
        }
        @Override
        public void visit(ObjectCreationExpr n, Void arg) {
            hasCall = true;
        }
        boolean hasCall() {
            return hasCall;
        }
    }

    // -------------------- 表达式处理 --------------------
    private void handleStatement(Statement stmt, List<CFGNode> incoming, CFGNode exit, 
                                boolean tryContext, List<CFGNode> catchIncoming) {
        if (stmt instanceof ExpressionStmt) {
            handleExpressionStmt((ExpressionStmt) stmt, incoming, exit, tryContext, catchIncoming);
        } else if (stmt instanceof ReturnStmt) {
            handleReturn((ReturnStmt) stmt, incoming, exit);
        } else if (stmt instanceof TryStmt) {
            handleTryCatch((TryStmt) stmt, incoming, exit);
        } else {
            processStatement(stmt, incoming, exit);
        }
    }

    private void handleExpressionStmt(ExpressionStmt stmt, List<CFGNode> incoming, 
                                     CFGNode exit, boolean tryContext, 
                                     List<CFGNode> catchIncoming) {
        Expression expr = stmt.getExpression();
        int beforeSize = incoming.size();
        if (expr instanceof MethodCallExpr) {
            handleMethodCall((MethodCallExpr) expr, incoming, tryContext, catchIncoming);
        } else if (expr instanceof AssignExpr) {
            handleAssignExpr((AssignExpr) expr, incoming);
        }
        if (incoming.size() == beforeSize) {
            linkToNext(incoming);
        }
    }

    private boolean isStaticMethodCall(MethodCallExpr call) {
        try {
            return call.resolve().isStatic();
        } catch (Exception e) {
            return call.getScope().isPresent() && 
                call.getScope().get().toString().matches("[A-Z][\\w.$]*");
        }
    }

    private String resolveClassName(MethodCallExpr call) {
        String className = "UnknownClass";
        try {
            Optional<Expression> scope = call.getScope();
            if (scope.isPresent()) {
                Expression scopeExpr = scope.get();
                className = scopeExpr.toString();
                if (scopeExpr instanceof NameExpr) {
                    try {
                        ResolvedType resolvedType = ((NameExpr) scopeExpr).calculateResolvedType();
                        className = resolvedType.asReferenceType().getQualifiedName();
                    } catch (Exception e) {}
                }
            }
        } catch (Exception e) {}
        return className;
    }

    private boolean isFullLogCall(MethodCallExpr call) {
        return call.getScope()
            .filter(scope -> {
                String scopeName = scope.toString();
                return scopeName.matches("(?i)(log(ger)?|LOG|LogUtil)") || 
                    scopeName.endsWith("Logger");
            })
            .isPresent() 
            && call.getNameAsString().matches("Trace|Debug|Info|Error|Fatal|TRACE|DEBUG|INFO|ERROR|FATAL|trace|debug|info|warn|error|fatal");
    }

    private String formatLogCall(MethodCallExpr call) {
        String callerChain = call.getScope()
            .map(scope -> scope.toString() + ".")
            .orElse("");
        return "LOG: " + callerChain + call.getNameAsString().toUpperCase() 
            + formatArgs(call.getArguments());
    }

    private String formatArgs(NodeList<Expression> args) {
        if (args.isEmpty()) return "";
        return ": " + args.stream()
            .map(arg -> {
                String argStr = arg.toString();
                return argStr.replaceAll("\"", "")
                            .replaceAll("\\s+", " ")
                            .replaceAll("\\$\\w+", "");
            })
            .collect(Collectors.joining(", "));
    }

    private void handleMethodCall(MethodCallExpr call, 
                            List<CFGNode> incoming,
                            boolean tryContext,
                            List<CFGNode> catchIncoming) {
        String methodName = call.getNameAsString();
        CFGNode callNode;
        if (isFullLogCall(call)) {
            callNode = createNode(formatLogCall(call));
        } else if (call.getScope().isPresent()) {
            String scopeName = call.getScope().get().toString();
            if (scopeName.matches(".*[A-Z].*")) {
                callNode = createNode("CALL: " + scopeName + "." + methodName);
            } else {
                callNode = createNode("CALL: " + methodName);
            }
        } else {
            callNode = createNode(isLogCall(call) ? "LOG: " + methodName : "CALL: " + methodName);
        }
        link(incoming, callNode);
        if (tryContext && catchIncoming != null) {
            CFGNode exceptionNode = createNode("EXCEPTION: " + methodName);
            callNode.addSuccessor(exceptionNode);
            catchIncoming.add(exceptionNode);
        }
        incoming.clear();
        incoming.add(callNode);
    }

    private void handleAssignExpr(AssignExpr assign, List<CFGNode> incoming) {
        analyzeExpression(assign.getValue(), incoming, 0);
    }

    private void link(List<CFGNode> sources, CFGNode target) {
        sources.forEach(s -> s.addSuccessor(target));
    }

    private List<CFGNode> processBranch(Statement stmt, CFGNode entry, CFGNode exit) {
        List<CFGNode> entries = new ArrayList<>();
        entries.add(entry);
        processStatement(stmt, entries, exit);
        return getExitNodes(entries);
    }

    private List<CFGNode> getExitNodes(List<CFGNode> nodes) {
        return nodes.stream()
            .flatMap(n -> n.successors.isEmpty() ? Stream.of(n) : n.successors.stream())
            .collect(Collectors.toList());
    }

    private void linkToExit(List<CFGNode> nodes, CFGNode exit) {
        nodes.forEach(n -> n.addSuccessor(exit));
    }

    private void linkToNext(List<CFGNode> incoming) {
        if (!incoming.isEmpty() && 
            incoming.stream().noneMatch(n -> n.label.startsWith("NEXT"))) {
            CFGNode next = createNode("NEXT");
            link(incoming, next);
            incoming.clear();
            incoming.add(next);
        }
    }

    private void analyzeExpression(Expression expr, List<CFGNode> context, int depth) {
        if (depth > MAX_RECURSION_DEPTH) return;
        expr.accept(new ExpressionVisitor(depth), context);
    }

    private class ExpressionVisitor extends VoidVisitorAdapter<List<CFGNode>> {
        private int depth;
        ExpressionVisitor(int depth) {
            this.depth = depth;
        }
        @Override
        public void visit(MethodCallExpr n, List<CFGNode> ctx) {
            if (depth > MAX_RECURSION_DEPTH) return;
            CFGNode callNode = createNode(isLogCall(n) ? "LOG: " + n.getName() : "CALL: " + n.getName());
            link(ctx, callNode);
            ctx.clear();
            ctx.add(callNode);
            for (Expression arg : n.getArguments()) {
                analyzeExpression(arg, ctx, depth + 1);
            }
            super.visit(n, ctx);
        }
        @Override
        public void visit(AssignExpr n, List<CFGNode> ctx) {
            if (depth > MAX_RECURSION_DEPTH) return;
            analyzeExpression(n.getValue(), ctx, depth + 1);
            analyzeExpression(n.getTarget(), ctx, depth + 1);
        }
        @Override
        public void visit(ObjectCreationExpr n, List<CFGNode> ctx) {
            CFGNode newNode = createNode("NEW: " + n.getType());
            link(ctx, newNode);
            ctx.clear();
            ctx.add(newNode);
            super.visit(n, ctx);
        }
    }

    private void handleLabeled(LabeledStmt stmt, List<CFGNode> incoming, CFGNode exit) {
        CFGNode labelNode = createNode("LABEL: " + stmt.getLabel());
        link(incoming, labelNode);
        processStatement(stmt.getStatement(), new ArrayList<>(Collections.singletonList(labelNode)), exit);
        incoming.clear();
        incoming.addAll(getExitNodes(new ArrayList<>(Collections.singletonList(labelNode))));
    }

    private void handleReturn(ReturnStmt stmt, List<CFGNode> incoming, CFGNode exit) {
        if (stmt.getExpression().isPresent()) {
            analyzeExpression(stmt.getExpression().get(), incoming, 0);
        }
        CFGNode returnNode = createNode("RETURN");
        link(incoming, returnNode);
        returnNode.addSuccessor(exit);
        incoming.clear();
    }

    private void handleBreak(BreakStmt stmt, List<CFGNode> incoming, CFGNode exit) {
        CFGNode breakNode = createNode("BREAK");
        link(incoming, breakNode);
        Optional<SimpleName> labelOpt = stmt.getLabel();
        if (labelOpt.isPresent()) {
            String label = labelOpt.get().asString();
            CFGNode target = labeledBreakMap.get(label);
            if (target != null) {
                breakNode.addSuccessor(target);
            } else {
                breakNode.addSuccessor(exit);
            }
        } else {
            if (!loopHeaderStack.isEmpty()) {
                CFGNode loopExit = createNode("LOOP_EXIT");
                breakNode.addSuccessor(loopExit);
                incoming.clear();
                incoming.add(loopExit);
            } else {
                breakNode.addSuccessor(exit);
                incoming.clear();
            }
        }
        incoming.clear();
    }

    private void handleContinue(ContinueStmt stmt, List<CFGNode> incoming, CFGNode exit) {
        CFGNode continueNode = createNode("CONTINUE");
        link(incoming, continueNode);
        Optional<SimpleName> labelOpt = stmt.getLabel();
        if (labelOpt.isPresent()) {
            String label = labelOpt.get().asString();
            CFGNode target = labeledContinueMap.get(label);
            if (target != null) {
                continueNode.addSuccessor(target);
            } else {
                continueNode.addSuccessor(exit);
            }
        } else {
            if (!loopHeaderStack.isEmpty()) {
                CFGNode loopHeader = loopHeaderStack.peek();
                continueNode.addSuccessor(loopHeader);
            } else {
                continueNode.addSuccessor(exit);
            }
        }
        incoming.clear();
    }

    private void handleThrow(ThrowStmt stmt, List<CFGNode> incoming, CFGNode exit) {
        CFGNode throwNode = createNode("THROW: " + stmt.getExpression());
        link(incoming, throwNode);
        throwNode.addSuccessor(exit);
        incoming.clear();
    }

    private boolean isLogCall(MethodCallExpr call) {
        String name = call.getNameAsString().toLowerCase();
        return name.contains("log");
    }

    private CFGNode createNode(String label) {
        return new CFGNode(label);
    }

    /**
     * 递归提取从入口到 EXIT 的所有路径（防止环路）。
     * 为防止无限递归，增加了最大路径深度限制。
     */
    public List<String> extractPaths(CFGNode node, String path, Set<CFGNode> visited, int depth) {
        List<String> paths = new ArrayList<>();
        if (depth > MAX_PATH_DEPTH) return paths;
        if (visited.contains(node)) return paths;
        visited.add(node);
        String labelToAdd = node.label.equals("NEXT") ? "" : node.toString();
        String newPath = path.isEmpty() ? labelToAdd : path + (labelToAdd.isEmpty() ? "" : " -> " + labelToAdd);
        if ("EXIT".equals(node.label)) {
            paths.add(newPath);
            return paths;
        }
        for (CFGNode successor : node.successors) {
            Set<CFGNode> newVisited = new HashSet<>(visited);
            paths.addAll(extractPaths(successor, newPath, newVisited, depth + 1));
        }
        return paths;
    }

    /**
     * 对外接口，返回给定代码的控制流路径列表，方便 py4j 调用。
     */
    public List<String> analyzeControlFlow(String code) {
        CFGNode cfgRoot = buildCFG(code);
        return extractPaths(cfgRoot, "", new HashSet<>(), 0);
    }

    public static void main(String[] args) {
        GatewayServer server = new GatewayServer(new JavaParserServer());
        server.start();
        System.out.println("CFG Generator Started");
    }
}
