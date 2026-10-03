# Java Interceptor 清单

## 1. Spring MVC 拦截器
- HandlerInterceptor
- HandlerInterceptorAdapter (旧版)
- AsyncHandlerInterceptor
- WebMvcConfigurer.addInterceptors(...)
- HandlerMethodArgumentResolver

## 2. Spring AOP / Method Interceptor
- org.aopalliance.intercept.MethodInterceptor
- org.springframework.aop.MethodBeforeAdvice
- org.springframework.aop.AfterReturningAdvice
- org.springframework.aop.ThrowsAdvice
- org.springframework.aop.framework.ProxyFactory

## 3. Spring WebFlux 拦截
- HandlerFilterFunction
- RouterFunction.filter(...)
- WebFilter (接近拦截器语义)
- GlobalFilter (Spring Cloud Gateway)
- GatewayFilter

## 4. Spring Security
- AbstractSecurityInterceptor
- FilterSecurityInterceptor
- MethodSecurityInterceptor
- PreAuthorize / PostAuthorize
- SecurityExpressionHandler

## 5. JAX-RS / Jersey / RESTEasy
- ContainerRequestFilter
- ContainerResponseFilter
- ReaderInterceptor
- WriterInterceptor
- ClientRequestFilter
- ClientResponseFilter

## 6. Struts2 / WebWork
- com.opensymphony.xwork2.interceptor.Interceptor
- com.opensymphony.xwork2.interceptor.AbstractInterceptor
- com.opensymphony.xwork2.interceptor.MethodFilterInterceptor
- com.opensymphony.xwork2.interceptor.PreResultListener

## 7. MyBatis / Hibernate
- MyBatis: org.apache.ibatis.plugin.Interceptor
- MyBatis: @Intercepts / @Signature
- Hibernate: org.hibernate.Interceptor
- Hibernate: EmptyInterceptor

## 8. 旧框架与安全相关拦截
- Apache Shiro: org.apache.shiro.aop.MethodInterceptor
- Apache Shiro: org.apache.shiro.aop.MethodInvocation
- Apache Shiro: org.apache.shiro.aop.AdviceFilter
- Apache Shiro: org.apache.shiro.aop.AnnotationMethodInterceptor
- Apache Shiro: org.apache.shiro.aop.MethodAnnotationResolver
- Apache Shiro: org.apache.shiro.aop.SpringAnnotationResolver
- Apache Shiro: org.apache.shiro.web.filter.authc.AuthenticatingFilter
- Apache Shiro: org.apache.shiro.web.filter.AccessControlFilter
- Apache Shiro: org.apache.shiro.web.filter.PathMatchingFilter
- SiteMesh: com.opensymphony.sitemesh.webapp.SiteMeshFilter (拦截视图)
- SiteMesh 3: org.sitemesh.webapp.SiteMeshFilter
- Wicket: IRequestCycleListener
- Wicket: IRequestCycleListener.onBeginRequest / onEndRequest
- Wicket: IRequestCycleListener.onRequestHandlerResolved
- Wicket: IRequestCycleListener.onRequestHandlerExecuted
- Wicket: RequestCycleListener.onBeginRequest()
- Wicket: RequestCycleListener.onEndRequest()
- Wicket: RequestCycleListener.onRequestHandlerScheduled(...)
- Wicket: RequestCycleListener.onRequestHandlerExecuted(...)
- Wicket: RequestCycleListener.onException(...)
- Wicket: RequestCycleListener.onDetach(...)
- Wicket: IComponentInstantiationListener
- JSF: javax.faces.event.PhaseListener
- JSF: javax.faces.event.PhaseEvent.getPhaseId()
- JSF: PhaseId.ANY_PHASE / RESTORE_VIEW / APPLY_REQUEST_VALUES
- JSF: PhaseId.PROCESS_VALIDATIONS / UPDATE_MODEL_VALUES
- JSF: PhaseId.INVOKE_APPLICATION / RENDER_RESPONSE
- JSF: javax.faces.event.SystemEventListener
- Struts1: org.apache.struts.action.RequestProcessor
- Struts1: RequestProcessor.processActionForm(...)
- Struts1: RequestProcessor.processValidate(...)
- Struts1: RequestProcessor.processPreprocess(...)
- Struts1: org.apache.struts.action.ActionServlet
- Apache CXF: org.apache.cxf.interceptor.Interceptor
- Apache CXF: org.apache.cxf.phase.PhaseInterceptor
- Apache CXF: org.apache.cxf.interceptor.InInterceptor
- Apache CXF: org.apache.cxf.interceptor.OutInterceptor
- Apache CXF: org.apache.cxf.interceptor.FaultInterceptor

## 9. 安全漏洞相关拦截器与 SQL 检查
- org.springframework.security.access.intercept.aopalliance.MethodSecurityInterceptor
- org.springframework.security.access.prepost.PreInvocationAuthorizationAdvice
- org.springframework.security.access.vote.AffirmativeBased
- org.hibernate.resource.jdbc.spi.StatementInspector
- org.hibernate.Interceptor.onPrepareStatement(...)
- MyBatis: org.apache.ibatis.executor.statement.StatementHandler
- MyBatis-Plus: com.baomidou.mybatisplus.extension.plugins.inner.IllegalSQLInnerInterceptor
- MyBatis-Plus: com.baomidou.mybatisplus.extension.plugins.inner.BlockAttackInnerInterceptor

## 10. 漏洞类型对应拦截器补充
- SQL 注入: StatementInspector / StatementHandler / IllegalSQLInnerInterceptor
- SSRF: org.springframework.http.client.ClientHttpRequestInterceptor
- SSRF: org.springframework.web.reactive.function.client.ExchangeFilterFunction
- XSS 输出: org.springframework.web.servlet.mvc.method.annotation.ResponseBodyAdvice
- 不安全重定向: HandlerInterceptor / HandlerMethodArgumentResolver
- 路径遍历: HandlerInterceptor / WebFilter

## 11. 漏洞类型对应常见框架/库
- SQL 注入: MyBatis Interceptor / MyBatis-Plus InnerInterceptor
- SQL 注入: Hibernate StatementInspector
- SQL 注入: JOOQ VisitListener
- SSRF: Spring Cloud Gateway GlobalFilter
- SSRF: OkHttp Interceptor
- XXE: JAXB Unmarshaller Listener
- XSS: OWASP Java HTML Sanitizer
- 反序列化: Jackson PolymorphicTypeValidator
- 模板注入: Thymeleaf Dialect 前置拦截
