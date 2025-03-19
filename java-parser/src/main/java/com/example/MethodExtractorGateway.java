package com.example;
import com.github.javaparser.*;
import com.github.javaparser.ast.CompilationUnit;
import com.github.javaparser.ast.body.ClassOrInterfaceDeclaration;
import com.github.javaparser.ast.body.MethodDeclaration;
import com.github.javaparser.ast.visitor.VoidVisitorAdapter;
import com.github.javaparser.ast.body.ConstructorDeclaration;
import py4j.GatewayServer;

public class MethodExtractorGateway {
    public static class MethodExtractor {
        /**
         * 根据文件代码内容进行解析（新版接口）
         */
        public String extractMethodFromCode(String code, String className, String methodName, String paramSignature) {
            try {
                CompilationUnit cu = StaticJavaParser.parse(code);
                MethodFinder finder = new MethodFinder(className, methodName, paramSignature);
                finder.visit(cu, null);
                return finder.getMethodCode();
            } catch (Exception e) {
                e.printStackTrace();
                return "ERROR: " + e.getMessage();
            }
        }

        static class MethodFinder extends VoidVisitorAdapter<Void> {
            private final String className;
            private final String methodName;
            private final String paramSignature;
            private String methodCode = null;

            public MethodFinder(String className, String methodName, String paramSignature) {
                this.className = className;
                this.methodName = methodName;
                this.paramSignature = paramSignature;
            }

            @Override
            public void visit(ClassOrInterfaceDeclaration classDecl, Void arg) {
                String normalizedClass = normalizeClassName(classDecl.getNameAsString());
                if (normalizedClass.equals(normalizeClassName(className))) {
                    System.out.println("Processing class: " + className);
                    // 先计算期望的归一化签名，如 "enterState(STATE)"
                    String expectedNormalized = normalizeSignature(methodName + paramSignature);
                    String fallbackMethodCode = null;

                    // 处理普通方法
                    for (MethodDeclaration method : classDecl.getMethods()) {
                        String extractedSignature = method.getSignature().asString();
                        String normExtracted = normalizeSignature(method.getNameAsString() + extractedSignature);
                        if (method.getNameAsString().equals(methodName)) {
                            fallbackMethodCode = method.toString();
                            if (normExtracted.equals(expectedNormalized)) {
                                methodCode = method.toString();
                                return;
                            }
                        }
                    }
                    // 处理构造函数

                    if ("<init>".equals(methodName)) {
                        for (ConstructorDeclaration constructor : classDecl.getConstructors()) {
                            String extractedSignature = constructor.getSignature().asString();
                            String constructorSignature = "<init>" + extractedSignature;
                            String normExtracted = normalizeSignature(constructorSignature);
                            if (normExtracted.equals(expectedNormalized)) {
                                methodCode = constructor.toString();
                                return;
                            }
                        }
                    }

                    // 如果没有精确匹配，但有同名候选，则退而求其次
                    if (methodCode == null && fallbackMethodCode != null) {
                        System.out.println("Fallback: using method name match only for " + methodName);
                        methodCode = fallbackMethodCode;
                    }
                }
                super.visit(classDecl, arg);
            }

            public String getMethodCode() {
                return methodCode;
            }
        }
    }

    /**
     * 归一化签名，将方法签名转换为 "methodName(param1,param2,...)" 格式，
     * 对于参数，移除包名和多余空白字符，例如：
     * "enterState(Service$STATE)" -> "enterState(STATE)"
     * "stopQuietly(org.slf4j.Logger, org.apache.hadoop.service.Service)" -> "stopQuietly(Logger,Service)"
     */
    private static String normalizeClassName(String className) {
        return className.replaceAll("\\$\\d+", "");  // 移除匿名类 $数字
    }
    private static String normalizeSignature(String signature) {
        signature = signature.replaceAll("\\s+", "").replaceAll("<.*?>", ""); // 去除空白和泛型
        int parenStart = signature.indexOf('(');
        int parenEnd = signature.indexOf(')');
        if (parenStart < 0 || parenEnd < 0 || parenEnd < parenStart) {
            return signature.replaceAll("\\s+", "");
        }
        String methodNamePart = signature.substring(0, parenStart).trim();
        String paramsPart = signature.substring(parenStart + 1, parenEnd).trim();
        if (paramsPart.isEmpty()) {
            return methodNamePart + "()";
        }
        String[] params = paramsPart.split(",");
        StringBuilder normalizedParams = new StringBuilder();
        for (int i = 0; i < params.length; i++) {
            String p = params[i].trim();
            // 若含有 "$"，则保留 "$" 后部分；否则若含有 "."，则保留最后一部分
            if (p.contains("$")) {
                p = p.substring(p.lastIndexOf('$') + 1);
            } else if (p.contains(".")) {
                p = p.substring(p.lastIndexOf('.') + 1);
            }
            normalizedParams.append(p);
            if (i < params.length - 1) {
                normalizedParams.append(",");
            }
        }
        return methodNamePart + "(" + normalizedParams.toString() + ")";
    }

    public static void main(String[] args) {
        MethodExtractor extractor = new MethodExtractor();
        GatewayServer server = new GatewayServer(extractor);
        server.start();
        System.out.println("Py4J Java Gateway Server Started...");
    }
}