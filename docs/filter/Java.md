# Java Filter / 中间件 清单

## 1. Servlet 规范过滤器
- javax.servlet.Filter
- javax.servlet.FilterChain
- javax.servlet.FilterConfig
- javax.servlet.ServletRequestWrapper
- javax.servlet.ServletResponseWrapper
- javax.servlet.http.HttpServletRequestWrapper
- javax.servlet.http.HttpServletResponseWrapper

## 2. Spring Web MVC 过滤与拦截
- OncePerRequestFilter
- GenericFilterBean
- DelegatingFilterProxy
- FilterRegistrationBean
- HandlerInterceptor
- HandlerInterceptorAdapter (旧版)
- WebMvcConfigurer.addInterceptors(...)
- HandlerMethodArgumentResolver

## 3. Spring Security 过滤链
- FilterChainProxy
- SecurityFilterChain
- SecurityContextPersistenceFilter
- UsernamePasswordAuthenticationFilter
- BasicAuthenticationFilter
- BearerTokenAuthenticationFilter
- OAuth2LoginAuthenticationFilter
- ExceptionTranslationFilter
- CsrfFilter
- HeaderWriterFilter

## 4. Spring WebFlux 过滤与拦截
- org.springframework.web.server.WebFilter
- org.springframework.web.server.WebFilterChain
- WebFilterChainProxy
- HandlerFilterFunction (Functional endpoints)
- RouterFunction.filter(...)
- GlobalFilter (Spring Cloud Gateway)
- GatewayFilter / GatewayFilterSpec

## 5. JAX-RS 过滤与拦截
- ContainerRequestFilter
- ContainerResponseFilter
- ClientRequestFilter
- ClientResponseFilter
- WriterInterceptor
- ReaderInterceptor

## 6. Struts2 过滤与拦截
- org.apache.struts2.dispatcher.filter.StrutsPrepareAndExecuteFilter
- org.apache.struts2.dispatcher.filter.StrutsPrepareFilter
- org.apache.struts2.dispatcher.filter.StrutsExecuteFilter
- com.opensymphony.xwork2.interceptor.Interceptor
- com.opensymphony.xwork2.interceptor.AbstractInterceptor

## 7. Micronaut / Quarkus 过滤
- io.micronaut.http.filter.HttpServerFilter
- io.micronaut.http.filter.ServerFilterPhase
- io.micronaut.http.filter.FilterRunner
- io.quarkus.vertx.http.runtime.filters.Filter
- io.quarkus.vertx.http.runtime.filters.FilterBuildItem
- io.quarkus.resteasy.reactive.server.spi.ResteasyReactiveContainerRequestFilter

## 8. Vert.x / Undertow / Netty
- io.vertx.ext.web.handler.HandlerInterceptor (基于 Handler)
- io.vertx.ext.web.RoutingContextHandler
- io.vertx.core.Handler<RoutingContext>
- io.undertow.server.HttpHandler
- io.undertow.server.handlers.PredicateHandler
- io.netty.channel.ChannelInboundHandler
- io.netty.handler.codec.http.HttpObjectAggregator

## 9. Play Framework / Jersey / RESTEasy
- play.mvc.Action
- play.mvc.EssentialFilter
- play.mvc.Filter
- org.glassfish.jersey.server.ContainerRequest
- org.glassfish.jersey.server.ContainerResponse
- org.jboss.resteasy.spi.interception.PreProcessInterceptor
- org.jboss.resteasy.spi.interception.MessageBodyReaderInterceptor

## 10. 老牌框架/自定义过滤
- Apache Shiro: org.apache.shiro.web.servlet.AbstractShiroFilter
- Apache Shiro: org.apache.shiro.web.filter.PathMatchingFilter
- Apache Shiro: org.apache.shiro.web.filter.authc.FormAuthenticationFilter
- Apache Shiro: org.apache.shiro.web.filter.authc.BasicHttpAuthenticationFilter
- Apache Shiro: org.apache.shiro.web.filter.AccessControlFilter
- Apache Shiro: org.apache.shiro.web.filter.mgt.DefaultFilterChainManager
- SiteMesh: com.opensymphony.sitemesh.webapp.SiteMeshFilter
- SiteMesh: com.opensymphony.sitemesh.webapp.SiteMeshWebAppContext
- SiteMesh 3: org.sitemesh.config.ConfigurableSiteMeshFilter
- SiteMesh 3: org.sitemesh.webapp.SiteMeshFilter
- WebWork: com.opensymphony.webwork.dispatcher.FilterDispatcher
- WebWork: com.opensymphony.webwork.dispatcher.ServletDispatcher
- WebWork: com.opensymphony.webwork.interceptor.Interceptor
- 自定义 Filter: implements javax.servlet.Filter

## 11. 安全漏洞相关过滤器与防护组件
- org.springframework.web.filter.CorsFilter
- org.springframework.security.web.csrf.CsrfFilter
- org.springframework.security.web.header.HeaderWriterFilter
- org.springframework.security.web.firewall.StrictHttpFirewall
- com.alibaba.druid.wall.WallFilter
- com.alibaba.druid.wall.WallConfig
- com.alibaba.druid.filter.FilterEventAdapter
- org.owasp.esapi.waf.ESAPIWebApplicationFirewall

## 12. 漏洞类型对应过滤器补充
- SQL 注入: com.alibaba.druid.wall.WallFilter / WallConfig
- 命令执行: 自定义 CommandInjectionFilter
- 路径遍历: 自定义 PathTraversalFilter
- SSRF: 自定义 UrlAllowlistFilter
- XXE: 自定义 XmlSecurityFilter
- 模板注入: 自定义 TemplateInputFilter
- 代码注入: 自定义 ScriptInjectionFilter
- 反序列化: java.io.ObjectInputFilter
- 不安全重定向: 自定义 RedirectValidationFilter
- XSS 输出: org.owasp.esapi.waf.ESAPIWebApplicationFirewall
- 日志注入: 自定义 LogSanitizerFilter

## 13. 漏洞类型对应常见框架/库
- SQL 注入: MyBatis-Plus IllegalSQLInnerInterceptor / Druid WallFilter
- SQL 注入: Hibernate StatementInspector
- SQL 注入: JPA @Query(nativeQuery) 统一拦截器
- SSRF: Spring Cloud Gateway GlobalFilter
- SSRF: Spring WebClient ExchangeFilterFunction
- SSRF: Apache HttpClient HttpRequestInterceptor
- XXE: Xerces SAXParser 安全特性过滤器
- XSS: AntiSamy Filter / ESAPI WAF
- 路径遍历: Spring ResourceHandlerInterceptor
- 不安全重定向: Spring Security RedirectStrategy 包装
- 反序列化: Jackson ObjectMapper 默认类型限制过滤
