# Sources and adoption boundaries

Read this file on demand for maintenance and traceability. It is not required for every implementation and does
not require network access or installation/execution of third-party tools. Only methods are borrowed below;
the text was originally reorganized in Chinese. Project standards, authorization and verification contracts retain authority.

## Karpathy community guidelines

- Original entry: [forrestchang/andrej-karpathy-skills](https://github.com/forrestchang/andrej-karpathy-skills);
  it redirected to `multica-ai/andrej-karpathy-skills` when checked.
- Primary file: [karpathy-guidelines/SKILL.md](https://github.com/multica-ai/andrej-karpathy-skills/blob/main/skills/karpathy-guidelines/SKILL.md).
  Its frontmatter declares `license: MIT`. This community project organizes Karpathy's observations;
  do not describe it as his official release.
- Adopted: distinguish assumptions explicitly, control change scope and judge completion by verifiable results.
- Not adopted: fixed line-count targets, a blanket ban on abstractions used once, stopping to ask about every
  question, or the examples' test-first steps. Judge abstraction, confirmation and new tests by actual boundaries
  and existing contracts.

## Vercel official engineering Skill

- Primary repository: [vercel-labs/agent-skills](https://github.com/vercel-labs/agent-skills).
- Primary file: [react-best-practices/SKILL.md](https://github.com/vercel-labs/agent-skills/blob/main/skills/react-best-practices/SKILL.md).
  The file credits `vercel` and declares `license: MIT`.
- Adopted: organize concerns by actual impact and use matching conditions to determine detailed reference reads.
- Not adopted: React/Next.js APIs, caching/rendering rules, dependencies, versions or that stack's risk ordering;
  do not generalize them into requirements for every language/project.

## 通用架构判断

- Microsoft Learn 的职责分离、显式依赖和依赖倒置用于判断业务规则与基础设施的耦合。是否引入接口或独立模块仍取决于项目中的真实收益。该文的工程示例属于 ASP.NET Core。[Architectural principles](https://learn.microsoft.com/en-us/dotnet/architecture/modern-web-apps-azure/architectural-principles)
- Go 官方指南按基础包、命令和服务端等用途说明布局，基础包可以从一个源码文件开始。根据真实使用者决定公开边界的做法可借鉴，`internal` 的导入限制及目录布局适用于 Go 模块。[Organizing a Go module](https://go.dev/doc/modules/layout)
- React 官方教程从界面与数据识别组件，保留最少的可变状态并确定持有者。可借鉴状态归属与派生值的判断，教程中的组件树、属性和状态 API 适用于 React。[Thinking in React](https://react.dev/learn/thinking-in-react)

## 设计模式案例

- Addison-Wesley 的出版页列出 GoF 原书的内容范围和章节分类，可作术语背景参考。这里的十二个案例由项目按日常工程场景选编。[Design Patterns 出版信息与目录](https://www.informit.com/store/design-patterns-elements-of-reusable-object-oriented-9780321700698)
- Microsoft Learn 的防腐层示例说明如何隔离两个系统间的语义差异。导入案例借鉴协议与错误映射的边界，部署形态由项目需要决定。[Anti-Corruption Layer pattern](https://learn.microsoft.com/en-us/azure/architecture/patterns/anti-corruption-layer)
- Oracle 的 Java `Comparator` 文档说明排序入口可以接收遵循同一比较契约的不同函数。策略案例借鉴这种替换方式，具体类型与缺省值规则沿用项目约定。[Comparator](https://docs.oracle.com/en/java/javase/26/docs/api/java.base/java/util/Comparator.html)
- W3C SCXML 用状态、事件和转换表达执行流程。任务案例借鉴这些概念，具体表示可用项目现有语言能力。AWS 的工程经验说明请求标识如何在结果未知时支持幂等重试，重试与结果核实仍按项目契约处理。[SCXML](https://www.w3.org/TR/scxml/)、[Making retries safe with idempotent APIs](https://aws.amazon.com/builders-library/making-retries-safe-with-idempotent-APIs/)
- Android 官方文档展示构造注入、工厂创建实例，以及 `AppContainer` 对不同作用域的管理。导出案例借鉴实例创建与依赖装配的分工，装配入口和工具选择由项目决定。[Manual dependency injection](https://developer.android.com/training/dependency-injection/manual)
- Oracle 的 Java `FilterInputStream` 文档展示输入流包装、读取转发与关闭传播。装饰器案例借鉴在已有契约上叠加能力的做法，资源归属和关闭语义沿用项目约定。[FilterInputStream](https://docs.oracle.com/en/java/javase/26/docs/api/java.base/java/io/FilterInputStream.html)

## Swift

- Swift 官方文档从调用处理解 API，并按声明、文件、模块或包管理可见性。用这些原则确认接口和真实消费者，访问级别以项目支持的语言版本为准。[API Design Guidelines](https://www.swift.org/documentation/api-design-guidelines/)、[Access Control](https://docs.swift.org/swift-book/documentation/the-swift-programming-language/accesscontrol/)
- Apple WWDC15 以协议要求说明可定制的行为，并用值语义说明状态如何独立传递。Swift 官方语言指南说明协议扩展的默认实现与结构体、枚举的值类型语义。详情页示例按实际替换点与状态需求应用这些机制。[Protocol-Oriented Programming in Swift](https://developer.apple.com/videos/play/wwdc2015/408/)、[Protocols](https://docs.swift.org/swift-book/documentation/the-swift-programming-language/protocols/)、[Structures and Classes](https://docs.swift.org/swift-book/documentation/the-swift-programming-language/classesandstructures/)
- Apple WWDC23 从测量入手处理性能问题，并用 `DogView` 说明如何缩小视图输入、减少无关更新。案例中的同文件放置建议来自职责和可见性判断。[Demystify SwiftUI performance](https://developer.apple.com/videos/play/wwdc2023/10160/)
- Apple 的 SwiftUI 数据模型示例用 Observation 让视图追踪它实际读取的模型属性。该能力从 iOS 17、macOS 14 等平台版本开始可用，采用方式取决于项目支持版本和已有的数据流。[Managing model data in your app](https://developer.apple.com/documentation/swiftui/managing-model-data-in-your-app)

## Kotlin

- Kotlin 官方文档以语义相关性判断源码聚合，按文件和模块控制可见性，并用结构化并发说明父子任务与取消的关系。项目将这些原则用于实际边界判断。上游的长度描述和示例依赖版本属于各自的指导语境。[Coding Conventions](https://kotlinlang.org/docs/coding-conventions.html#source-file-organization)、[Visibility modifiers](https://kotlinlang.org/docs/visibility-modifiers.html)、[Coroutines basics](https://kotlinlang.org/docs/coroutines-basics.html#coroutine-scope-and-structured-concurrency)
- Kotlin 官方文档说明顶层函数、密封类型与穷尽的 `when`，以及用 `by` 转发接口成员。根据实际状态集合、调用路径、转发收益和项目语言版本采用。[Functions](https://kotlinlang.org/docs/functions.html#function-scope)、[Sealed classes and interfaces](https://kotlinlang.org/docs/sealed-classes.html)、[Delegation](https://kotlinlang.org/docs/delegation.html)
- Android 官方架构建议按适用收益在屏幕级使用 Jetpack `ViewModel`，在可复用组件使用普通状态持有类。做法按状态归属、生命周期和项目实际框架版本选择。[Recommendations for Android architecture](https://developer.android.com/topic/architecture/recommendations)
- Now in Android 样例固定提交 `2982e63cb691ad49cd009aab43dc206fee6699c2`，Apache-2.0。核对了「For You」的导航、状态收集、事件、仓库写入和收藏状态测试。参考同一职责下的源码组织，以及 Android 生命周期与写入归属的对应关系。[导航入口](https://github.com/android/nowinandroid/blob/2982e63cb691ad49cd009aab43dc206fee6699c2/feature/foryou/impl/src/main/kotlin/com/google/samples/apps/nowinandroid/feature/foryou/impl/navigation/ForYouEntryProvider.kt)、[ForYouScreen.kt](https://github.com/android/nowinandroid/blob/2982e63cb691ad49cd009aab43dc206fee6699c2/feature/foryou/impl/src/main/kotlin/com/google/samples/apps/nowinandroid/feature/foryou/impl/ForYouScreen.kt)、[ForYouViewModel.kt](https://github.com/android/nowinandroid/blob/2982e63cb691ad49cd009aab43dc206fee6699c2/feature/foryou/impl/src/main/kotlin/com/google/samples/apps/nowinandroid/feature/foryou/impl/ForYouViewModel.kt)、[ForYouViewModelTest.kt](https://github.com/android/nowinandroid/blob/2982e63cb691ad49cd009aab43dc206fee6699c2/feature/foryou/impl/src/test/kotlin/com/google/samples/apps/nowinandroid/feature/foryou/impl/ForYouViewModelTest.kt)、[LICENSE](https://github.com/android/nowinandroid/blob/2982e63cb691ad49cd009aab43dc206fee6699c2/LICENSE)

## Python

- PEP 8 说明公开与内部接口的表达方式，PEP 257 建议在文档字符串中记录调用契约。遵循实际项目的导出和文档约定，并检查真实消费者。[PEP 8 Public and Internal Interfaces](https://peps.python.org/pep-0008/#public-and-internal-interfaces)、[PEP 257 Multi-line Docstrings](https://peps.python.org/pep-0257/#multi-line-docstrings)
- Python 官方教程说明模块如何组织并复用定义。语言参考说明 `with` 如何在作用域内调用上下文管理器。PEP 544 说明静态结构化子类型和它的运行时边界，采用方式取决于项目现有类型检查与调用契约。[Modules](https://docs.python.org/3/tutorial/modules.html)、[The with statement](https://docs.python.org/3/reference/compound_stmts.html#the-with-statement)、[PEP 544](https://peps.python.org/pep-0544/)
- FastAPI 多文件教程固定提交 `b2831196bfee3eb9ce303a3c6440f2a104832954`，MIT。查看应用入口如何装配路由和依赖，以及 `TestClient` 执行的 HTTP 路由契约测试。分组方式与依赖声明适用于 FastAPI，教程内存数据和令牌是演示数据。[官方教程](https://fastapi.tiangolo.com/tutorial/bigger-applications/)、[main.py](https://github.com/fastapi/fastapi/blob/b2831196bfee3eb9ce303a3c6440f2a104832954/docs_src/bigger_applications/app/main.py)、[items.py](https://github.com/fastapi/fastapi/blob/b2831196bfee3eb9ce303a3c6440f2a104832954/docs_src/bigger_applications/app/routers/items.py)、[HTTP 入口测试](https://github.com/fastapi/fastapi/blob/b2831196bfee3eb9ce303a3c6440f2a104832954/tests/test_tutorial/test_bigger_applications/test_main.py)、[LICENSE](https://github.com/fastapi/fastapi/blob/b2831196bfee3eb9ce303a3c6440f2a104832954/LICENSE)
- pytest 的 fixture 指南固定提交 `36eed6b7b0eb59760fc4b33e90bdaac5057388f0`，MIT。核对安全清理示例中独立准备与清理资源的做法。fixture 的写法与作用域是 pytest 的测试机制。[官方指南](https://docs.pytest.org/en/stable/how-to/fixtures.html#safe-fixture-structure)、[固定示例](https://github.com/pytest-dev/pytest/blob/36eed6b7b0eb59760fc4b33e90bdaac5057388f0/doc/en/how-to/fixtures.rst#L880)、[LICENSE](https://github.com/pytest-dev/pytest/blob/36eed6b7b0eb59760fc4b33e90bdaac5057388f0/LICENSE)

## Go

- Go 模块布局文档说明包、命令和 `internal` 的组织方式。Effective Go 用方法集与小型接口解释隐式满足。Go 项目的代码评审建议从接口使用方确定方法范围，并让实现侧可以返回具体类型。[Organizing a Go module](https://go.dev/doc/modules/layout)、[Effective Go · Interfaces](https://go.dev/doc/effective_go#interfaces)、[Go Code Review Comments · Interfaces](https://go.dev/wiki/CodeReviewComments#interfaces)
- Go 官方博客说明检查返回的 `error`、提供诊断上下文，以及包装错误可能带来的 API 兼容承诺。[Error handling and Go](https://go.dev/blog/error-handling-and-go)、[Working with Errors in Go 1.13](https://go.dev/blog/go1.13-errors#Whether_to_Wrap)

## Local sampling and maintenance

Applicability has been checked against project standards and real modules/tests across different stacks.
Specific projects, source locations and session evidence remain in task handoffs. They are not prerequisites
for using this Skill. Do not copy business rules or machine paths, or infer a universal framework, version or
visual style from examples.

For later updates, check the provenance and license declarations of the files actually adopted. If copying
third-party text/code, retain the applicable license and attribution for that version. Current content introduces
no mandatory TDD, additional review, commit or release process.
