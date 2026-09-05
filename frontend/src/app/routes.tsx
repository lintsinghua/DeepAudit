import { lazy } from "react";
const Dashboard = lazy(() => import("@/pages/Dashboard"));
const Projects = lazy(() => import("@/pages/Projects"));
const ProjectDetail = lazy(() => import("@/pages/ProjectDetail"));
const RecycleBin = lazy(() => import("@/pages/RecycleBin"));
const InstantAnalysis = lazy(() => import("@/pages/InstantAnalysis"));
const AuditTasks = lazy(() => import("@/pages/AuditTasks"));
const TaskDetail = lazy(() => import("@/pages/TaskDetail"));
const AgentAudit = lazy(() => import("@/pages/AgentAudit"));
const AdminDashboard = lazy(() => import("@/pages/AdminDashboard"));
const Account = lazy(() => import("@/pages/Account"));
const AuditRules = lazy(() => import("@/pages/AuditRules"));
const PromptManager = lazy(() => import("@/pages/PromptManager"));
import type { ReactNode } from 'react';

export interface RouteConfig {
  name: string;
  path: string;
  element: ReactNode;
  visible?: boolean;
}

const routes: RouteConfig[] = [
  {
    name: "Agent审计",
    path: "/",
    element: <AgentAudit />,
    visible: true,
  },
  {
    name: "Agent审计任务",
    path: "/agent-audit/:taskId",
    element: <AgentAudit />,
    visible: false,
  },
  {
    name: "仪表盘",
    path: "/dashboard",
    element: <Dashboard />,
    visible: true,
  },
  {
    name: "项目管理",
    path: "/projects",
    element: <Projects />,
    visible: true,
  },
  {
    name: "项目详情",
    path: "/projects/:id",
    element: <ProjectDetail />,
    visible: false,
  },
  {
    name: "即时分析",
    path: "/instant-analysis",
    element: <InstantAnalysis />,
    visible: true,
  },
  {
    name: "审计任务",
    path: "/audit-tasks",
    element: <AuditTasks />,
    visible: true,
  },
  {
    name: "任务详情",
    path: "/tasks/:id",
    element: <TaskDetail />,
    visible: false,
  },
  {
    name: "审计规则",
    path: "/audit-rules",
    element: <AuditRules />,
    visible: true,
  },
  {
    name: "提示词管理",
    path: "/prompts",
    element: <PromptManager />,
    visible: true,
  },
  {
    name: "系统管理",
    path: "/admin",
    element: <AdminDashboard />,
    visible: true,
  },
  {
    name: "回收站",
    path: "/recycle-bin",
    element: <RecycleBin />,
    visible: true,
  },
  {
    name: "账号管理",
    path: "/account",
    element: <Account />,
    visible: false, // 不在主导航显示，在侧边栏底部单独显示
  },
];

export default routes;