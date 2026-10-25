export default {
  mcpTokens: {
    "title": "MCP Token",
    "scope": "Token 可只读查询全部现有及未来新增的词库目录。",
    "refresh": "刷新",
    "create": "创建 Token",
    "empty": "暂无 MCP Token",
    "previous": "上一页",
    "next": "下一页",
    "page": "第 {page} 页",
    "name": "名称",
    "id": "Token ID",
    "createdBy": "创建者",
    "createdAt": "创建时间",
    "expiresAt": "到期时间",
    "status": "状态",
    "actions": "操作",
    "active": "有效",
    "expired": "已过期",
    "revoked": "已撤销",
    "revoke": "撤销",
    "validity": "有效期",
    "days": "{days} 天",
    "custom": "自定义日期",
    "secretTitle": "复制您的 Token",
    "secretWarning": "完整 Token 仅显示这一次。请立即复制，关闭后无法再次查看。",
    "endpoint": "MCP 地址",
    "copy": "复制 Token",
    "close": "关闭",
    "revokeWarning": "撤销不可逆。使用此 Token 的客户端将失去访问权限；需创建新 Token 恢复访问。",
    "loadError": "无法加载 Token。",
    "createError": "无法创建 Token。如响应丢失，请刷新列表并撤销新凭证后再创建。",
    "nameRequired": "请输入名称（1–100 个字符）。",
    "expiryRequired": "请选择未来的到期时间。",
    "copied": "Token 已复制",
    "copyError": "复制失败，请手动选中并复制 Token。",
    "revokeError": "无法撤销 Token。",
    "revokedSuccess": "Token 已撤销"
},
  // Application
  app: {
    title: '文档翻译'
  },

  // Navigation
  nav: {
    mcpTokens: "MCP Token",
    main: '翻译',
    dashboard: '仪表盘',
    settings: '设置',
    thesaurus: '术语库',
    users: '用户管理',
    logout: '退出登录',
    logoutSuccess: '退出成功',
    seeYou: '下次再见！'
  },

  // Login Page
  login: {
    username: '用户名',
    password: '密码',
    submit: '登录',
    submitting: '登录中...',
    error: '用户名或密码错误',
    required: '请输入{field}',
    welcome: '欢迎回来',
    welcomeSubtitle: '请输入您的登录信息。',
    success: '登录成功',
    welcomeBack: '欢迎回来！'
  },

  // Main Page - File Upload
  fileUpload: {
    title: '文件上传',
    dragDrop: '拖拽文件到此处或点击上传',
    selectedFiles: '已选择的文件',
    remove: '移除',
    invalidFormat: '支持的格式：.xlsx, .docx, .pptx, .pdf, .txt, .md',
    uploading: '上传中...',
    uploadComplete: '上传完成',
    uploadSuccess: '成功上传 {count} 个文件{failed}',
    failed: '失败'
  },

  // Main Page - Language Pair
  languagePair: {
    title: '语言对',
    select: '选择语言对'
  },

  // Main Page - Translation
  translation: {
    title: '翻译',
    subtitle: '上传您的文档并立即翻译。',
    start: '开始翻译',
    actionDescription: '准备好翻译了吗？点击下方按钮开始。',
    validationUpload: '请至少上传一个文档',
    validationLanguage: '请选择语言对'
  },

  // Dashboard Page
  dashboard: {
    title: '仪表盘',
    subtitle: '查看您的翻译统计信息和词汇库概览。',
    translatedDocs: '已翻译文档',
    translatedDocsDesc: '成功完成翻译的文件数量',
    termPairs: '术语对数量',
    termPairsDesc: '已配置的源术语和译文术语对',
    translatedItems: '已翻译段落数',
    translatedItemsDesc: '多格式文档中已成功翻译的总片段数',
    termCatalogs: '术语目录数',
    termCatalogsDesc: '用于组织术语对的词汇库目录数量',
    noData: '暂无统计数据'
  },

  // Job
  job: {
    history: '已翻译文件',
    noJobs: '暂无已完成的任务',
    files: '个文件',
    failedFiles: '失败的文件',
    translationWarnings: '翻译警告',
    totalJobs: '共 {count} 个任务',
    started: '翻译已开始',
    startedDesc: '您的文件正在翻译中。',
    completed: '翻译完成',
    completedDesc: '已成功翻译 {filesCompleted} 个文件。',
    completedWithWarnings: '翻译完成（有警告）',
    completedWithWarningsDesc: '已翻译 {filesCompleted} 个文件，但 {warningFiles} 个文件中有 {failedSegments} 个片段翻译失败。',
    partialSuccess: '翻译部分完成',
    partialSuccessDesc: '{filesCompleted} 个文件成功，{filesFailed} 个文件失败。',
    failed: '翻译失败',
    failedDesc: '请检查错误详情。'
  },

  // Progress Tracker
  progress: {
    title: '翻译进度',
    overall: '总体进度',
    currentFile: '当前文件',
    filesCompleted: '个文件已完成',
    segments: '段落',
    errors: '错误',
    warnings: '警告',
    jobTitle: '翻译任务',
    loading: '正在加载任务状态...',
    noActiveJob: '没有进行中的翻译任务',
    started: '开始时间',
    completed: '完成时间'
  },

  // File Download
  download: {
    button: '下载'
  },

  // Settings Page
  settings: {
    translationTab: '翻译设置',
    subtitle: '管理翻译模型和语言配置。',
    languagePairs: '语言对管理',
    addLanguagePair: '添加语言对',
    sourceLanguage: '源语言',
    targetLanguage: '目标语言',
    sourceCode: '源语言代码',
    targetCode: '目标语言代码',
    noLanguagePairs: '暂无配置的语言对',
    uiLanguage: '界面语言',
    translationModel: '翻译模型',
    selectModel: '选择AI模型',
    currentModel: '当前使用的模型',
    configuredPairs: '已配置的语言对',
    confirmDelete: '确定要删除这个语言对吗？',
    appearance: '外观',
    // Validation messages
    validation: {
      sourceLanguageRequired: '请输入源语言',
      targetLanguageRequired: '请输入目标语言',
      sourceCodeRequired: '请输入源语言代码',
      targetCodeRequired: '请输入目标语言代码',
      languageNameMinLength: '语言名称至少2个字符',
      codeLength: '语言代码必须是2-5个字符',
      codeFormat: '语言代码只能是小写字母'
    },
    // Message keys
    loadLanguagePairsError: '加载语言对失败',
    languagePairExists: '此语言对已存在',
    languagePairAdded: '语言对添加成功',
    languagePairAddError: '添加语言对失败',
    languagePairRemoved: '语言对移除成功',
    languagePairRemoveError: '移除语言对失败',
    loadModelError: '加载模型配置失败',
    modelUpdated: '模型已更新为 {modelName}',
    updateModelError: '更新模型失败'
  },

  // Validation
  validation: {
    required: '此字段为必填项',
    tooLong: '输入内容过长',
    tooShort: '输入内容过短'
  },

  // Common
  common: {
    cancel: '取消',
    save: '保存',
    delete: '删除',
    edit: '编辑',
    add: '添加',
    yes: '是',
    no: '否',
    ok: '确定',
    to: '到',
    optional: '可选',
    actions: '操作'
  },

  // Thesaurus
  thesaurus: {
    title: '术语库',
    subtitle: '管理翻译术语对，确保术语一致性。',
    languageAndCatalog: '语言和目录',
    catalog: '目录',
    selectCatalog: '选择目录',
    termPairs: '术语对',
    sourceTerm: '源术语',
    targetTerm: '目标术语',
    lastModified: '最后修改',
    addTerm: '添加术语',
    editTerm: '编辑术语',
    import: '导入 CSV',
    export: '导出 CSV',
    searchPlaceholder: '搜索源术语...',
    selectLanguagePairFirst: '请先选择语言对',
    selectCatalogFirst: '请选择或创建目录',
    confirmDelete: '删除此术语对？',
    termDeleted: '术语删除成功',
    termAdded: '术语添加成功',
    termUpdated: '术语更新成功',
    exportSuccess: '导出完成',
    catalogNamePlaceholder: '例如：IT术语',
    catalogs: '目录',
    confirmDeleteCatalog: '删除此目录及其所有术语？',
    catalogCreated: '目录创建成功',
    catalogRenamed: '目录重命名成功',
    catalogDeleted: '目录已删除',
    catalogDeletedTerms: '同时删除了 {count} 个术语',
    totalTerms: '共 {total} 个术语',
    sourceTermPlaceholder: '输入源术语',
    targetTermPlaceholder: '输入目标术语翻译',
    sourceTermReadonly: '编辑时无法更改源术语',
    emptyTermError: '术语不能为空或仅包含空格',
    termTooLong: '术语不能超过500个字符',
    importTerms: '从 CSV 导入术语',
    dragCsvHere: '点击或拖拽 CSV 文件到此区域',
    csvFormat: 'CSV 必须包含列：source_term, target_term',
    preview: '预览',
    rows: '行',
    parseWarnings: '部分行存在问题',
    importNow: '立即导入',
    importComplete: '导入完成',
    created: '已创建',
    updated: '已更新',
    skipped: '已跳过',
    viewErrors: '查看错误',
    emptyFile: '文件为空',
    insufficientColumns: '列数不足',
    emptyTerms: '源术语或目标术语为空',
    catalogSelectorHelp: '选择用于翻译的目录。拖动以调整优先级。',
    noCatalogsAvailable: '此语言对没有可用目录',
    availableCatalogs: '可用',
    selectedCatalogs: '已选择',
    dragToReorder: '（拖动调整优先级）',
    totalTermsSelected: '术语总数',
    termLimitWarning: '仅匹配到的术语会注入提示词',
    termCatalogs: '术语目录'
  },

  // Output Mode
  outputMode: {
    label: '输出模式',
    tooltip: '替换：仅保留译文。追加：原文在前，译文在后。前置：译文在前，原文在后。交错：逐行交替，原文在前。交错（反转）：逐行交替，译文在前。',
    replace: '替换',
    append: '追加',
    prepend: '前置',
    interleave: '交错',
    interleave_reverse: '交错（反转）'
  },

  // Error Messages
  error: {
    unknown: '未知错误',
    // ErrorDisplay component
    retrying: '重试中...',
    retry: '重试',
    defaultTitle: '错误',
    unexpectedError: '发生意外错误'
  },

  // Not Found Page
  notFound: {
    title: '404',
    subtitle: '抱歉，您访问的页面不存在。',
    backHome: '返回首页',
    goBack: '返回上页'
  },

  // User Management
  userManagement: {
    title: '用户管理',
    subtitle: '管理系统用户账户',
    createUser: '创建用户',
    editUser: '编辑用户',
    deleteUser: '删除用户',
    confirmDelete: '确定要删除用户 "{username}" 吗？',
    username: '用户名',
    password: '密码',
    confirmPassword: '确认密码',
    role: '角色',
    status: '状态',
    createdAt: '创建时间',
    currentUser: '当前用户',
    noUsers: '暂无用户',
    unlock: '解锁',
    usernamePlaceholder: '请输入用户名',
    passwordPlaceholder: '请输入密码',
    passwordEditPlaceholder: '留空表示不修改',
    confirmPasswordPlaceholder: '请再次输入密码',
    usernameLength: '用户名长度3-50字符',
    usernameFormat: '只允许字母、数字、下划线',
    passwordMinLength: '密码至少6个字符',
    cannotChangeOwnRole: '不能修改自己的角色',
    createSuccess: '用户创建成功',
    createError: '创建失败',
    updateSuccess: '用户更新成功',
    updateError: '更新失败',
    deleteSuccess: '用户删除成功',
    deleteError: '删除失败',
    unlockSuccess: '用户解锁成功',
    unlockError: '解锁失败',
    roles: {
      admin: '管理员',
      user: '普通用户'
    },
    statuses: {
      PENDING_PASSWORD: '待修改密码',
      ACTIVE: '活跃',
      LOCKED: '已锁定',
      DELETED: '已删除'
    },
    errors: {
      userAlreadyExists: '用户名已存在'
    }
  },

  // Change Password
  changePassword: {
    title: '修改密码',
    subtitle: '首次登录需要修改密码才能继续使用系统',
    currentPassword: '当前密码',
    newPassword: '新密码',
    confirmPassword: '确认新密码',
    currentPasswordPlaceholder: '请输入当前密码',
    newPasswordPlaceholder: '请输入新密码',
    confirmPasswordPlaceholder: '请再次输入新密码',
    submit: '确认修改',
    strength: {
      weak: '弱',
      medium: '中',
      strong: '强'
    },
    errors: {
      invalidCurrentPassword: '当前密码错误',
      passwordSameAsOld: '新密码不能与旧密码相同',
      passwordMismatch: '两次输入的密码不一致'
    },
    success: '密码修改成功'
  }

}
