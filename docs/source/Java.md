# Java 漏洞 Source 点清单

## 1. Web 请求参数（Servlet/JAX-RS/Spring）
- HttpServletRequest.getParameter(...)
- HttpServletRequest.getParameterValues(...)
- HttpServletRequest.getParameterMap()
- HttpServletRequest.getHeader(...)
- HttpServletRequest.getHeaders(...)
- HttpServletRequest.getQueryString()
- HttpServletRequest.getCookies()
- HttpServletRequest.getInputStream()
- HttpServletRequest.getReader()
- @RequestParam / @RequestHeader / @CookieValue
- @PathVariable / @MatrixVariable
- JAX-RS: @QueryParam / @PathParam / @HeaderParam / @CookieParam / @FormParam
- Spring WebFlux: ServerRequest.queryParam(...)
- Spring WebFlux: ServerRequest.bodyToMono(...)
- Spring MVC: @RequestBody / @RequestParam / @PathVariable / @RequestHeader
- Spring MVC: WebRequest.getParameter(...)
- Spring MVC: NativeWebRequest.getParameter(...)
- Spring Cloud Gateway: ServerWebExchange.getRequest().getQueryParams()
- Spring Cloud Gateway: ServerWebExchange.getRequest().getHeaders()
- Micronaut: @QueryValue / @PathVariable / @Body / @Header
- Micronaut: HttpRequest.getParameters()
- Quarkus: @QueryParam / @PathParam / @HeaderParam / @FormParam
- Quarkus: RoutingContext.request().getParam(...)
- Play Framework: request.getQueryString(...)
- Play Framework: request.body().asJson()
- Vert.x: RoutingContext.request().getParam(...)
- Vert.x: RoutingContext.getBodyAsString()
- Jersey: ContainerRequestContext.getHeaders()

## 2. 请求体/表单/JSON 反序列化
- @RequestBody 绑定的 DTO/Map/JsonNode
- ObjectMapper.readValue(InputStream, ...)
- ObjectMapper.readTree(...)
- Gson.fromJson(...)
- Jackson 的 JsonNode.get(...) 读取客户端字段
- MultipartFile.getInputStream()
- MultipartFile.getBytes()
- Jackson: ObjectReader.readValue(...)
- Jackson: ObjectMapper.convertValue(...)
- Fastjson: JSON.parseObject(...)
- Fastjson: JSONObject.getString(...)
- org.json: new JSONObject(body).get(...)
- Protobuf: request.getXxx() (protobuf message)
- Spring WebFlux: ServerRequest.bodyToFlux(...)

## 3. 文件上传与多部件表单
- MultipartFile.getOriginalFilename()
- MultipartFile.getInputStream()
- Part.getInputStream()
- Part.getSubmittedFileName()
- DiskFileItem.getInputStream()
- Commons FileUpload: FileItem.getName()
- Commons FileUpload: FileItem.getInputStream()
- Servlet 3.0: request.getParts()
- Spring: MultipartHttpServletRequest.getFile(...)

## 4. URL/路径相关输入
- HttpServletRequest.getRequestURI()
- HttpServletRequest.getRequestURL()
- HttpServletRequest.getPathInfo()
- HttpServletRequest.getServletPath()
- ServerHttpRequest.getPath()

## 5. 认证/会话/Token 输入
- HttpServletRequest.getRemoteUser()
- HttpServletRequest.getUserPrincipal().getName()
- HttpSession.getAttribute(...)
- SecurityContextHolder.getContext().getAuthentication().getName()
- OAuth2AuthenticationToken.getPrincipal().getAttributes()
- Jwt.getClaimAsString(...)

## 6. RPC/微服务输入
- gRPC: request.getXxx()
- Dubbo: 参数对象 getter
- Spring Cloud OpenFeign: 请求参数绑定对象
- Spring Cloud: @RequestBody / @RequestParam 绑定 DTO
- Apache Thrift: request.getXxx()
- Hessian: 反序列化后的参数对象
- RSocket: Payload.getDataUtf8()

## 7. 模板/表达式输入
- Spring EL: ${param.xxx} / ${header.xxx}
- Thymeleaf: ${param.xxx} / ${#request.getParameter(...)}
- Velocity: $request.getParameter(...)
- Freemarker: RequestParameters / request
- Spring EL: #request, #session, #params
- JSP EL: ${param.xxx} / ${header.xxx} / ${cookie.xxx}
- Pebble: {{ request.parameter("...") }}

## 8. 消息队列/事件流输入
- Kafka ConsumerRecord.value()
- RabbitMQ Message.getBody()
- RocketMQ Message.getBody()
- Pulsar Message.getData()
- Spring Kafka: @Payload String
- Spring AMQP: Message.getMessageProperties().getHeaders()
- Spring Cloud Stream: @StreamListener 参数

## 9. 数据库中不可信字段
- ResultSet.getString(...)
- ResultSet.getObject(...)
- ORM 实体字段来自外部同步数据源
- JpaRepository 查询结果字段
- MyBatis ResultMap 字段

## 10. 外部系统/配置输入
- System.getenv(...)
- System.getProperty(...)
- Properties.getProperty(...)
- JNDI: InitialContext.lookup(...)
- Spring Environment.getProperty(...)
- Spring Cloud Config: Environment.getProperty(...)
- Vault: Logical.read(...)
- Consul: KVClient.getValue(...)

## 11. 框架细分（Spring Security / Spring Cloud Gateway）
- Spring Security: SecurityContextHolder.getContext().getAuthentication()
- Spring Security: Authentication.getPrincipal() / getCredentials() / getDetails()
- Spring Security: HttpSecurity.oauth2Login().userInfoEndpoint() 返回的用户属性
- Spring Security: OAuth2AuthenticationToken.getPrincipal().getAttributes()
- Spring Security: JwtAuthenticationToken.getTokenAttributes()
- Spring Security: Jwt.getClaim(...) / getClaimAsString(...)
- Spring Security: ReactiveSecurityContextHolder.getContext()
- Spring Cloud Gateway: ServerWebExchange.getRequest().getQueryParams()
- Spring Cloud Gateway: ServerWebExchange.getRequest().getHeaders()
- Spring Cloud Gateway: ServerWebExchange.getRequest().getCookies()
- Spring Cloud Gateway: ServerWebExchange.getRequest().getBody()
- Spring Cloud Gateway: ServerHttpRequest.getURI().getRawQuery()

## 12. 框架细分（Spring WebFlux / Struts2 / Micronaut / Quarkus）
- Spring WebFlux: ServerRequest.queryParam(...)
- Spring WebFlux: ServerRequest.pathVariable(...)
- Spring WebFlux: ServerRequest.headers().firstHeader(...)
- Spring WebFlux: ServerRequest.cookies()
- Spring WebFlux: ServerRequest.bodyToMono(...)
- Spring WebFlux: ServerWebExchange.getRequest().getQueryParams()
- Spring WebFlux: ServerWebExchange.getRequest().getHeaders()
- Spring WebFlux: ServerWebExchange.getRequest().getBody()
- Struts2: ActionContext.getContext().getParameters()
- Struts2: ServletActionContext.getRequest().getParameter(...)
- Struts2: ServletActionContext.getRequest().getHeader(...)
- Struts2: ActionContext.getContext().getName()
- Struts2: ValueStack.findValue(...)
- Micronaut: HttpRequest.getParameters()
- Micronaut: HttpRequest.getHeaders().get(...)
- Micronaut: HttpRequest.getBody()
- Micronaut: @Body / @QueryValue / @PathVariable
- Quarkus: RoutingContext.request().getParam(...)
- Quarkus: RoutingContext.request().getHeader(...)
- Quarkus: RoutingContext.getBodyAsString()
- Quarkus: @QueryParam / @PathParam / @HeaderParam

## 13. 其他老牌 Java Web 框架
- WebWork: ActionContext.getContext().getParameters()
- Tapestry: Request.getParameter(...)
- Wicket: RequestCycle.get().getRequest().getRequestParameters()
- JSF: FacesContext.getCurrentInstance().getExternalContext().getRequestParameterMap()
- Apache CXF: Message.getContextualProperty(...)
- Spring MVC 早期: HttpServletRequest.getParameter(...)
