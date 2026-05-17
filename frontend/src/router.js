import { createRouter, createWebHashHistory } from 'vue-router'

const routes = [
  { path: '/', redirect: '/dashboard' },
  { path: '/login', component: () => import('./views/Login.vue'), meta: { public: true } },
  {
    path: '/',
    component: () => import('./views/Layout.vue'),
    children: [
      { path: 'dashboard', component: () => import('./views/Dashboard.vue') },
      { path: 'tokens', component: () => import('./views/Tokens.vue') },
      { path: 'notice', component: () => import('./views/Notice.vue') },
      { path: 'prompts', component: () => import('./views/Prompts.vue') },
      { path: 'models', component: () => import('./views/Models.vue') },
      { path: 'groups', component: () => import('./views/Groups.vue') },
      { path: 'orders', component: () => import('./views/Orders.vue') },
      { path: 'users', component: () => import('./views/Users.vue') },
      { path: 'settings', component: () => import('./views/Settings.vue') },
    ]
  }
]

const router = createRouter({ history: createWebHashHistory(), routes })

router.beforeEach((to) => {
  if (!to.meta.public && !localStorage.getItem('admin_token')) {
    return '/login'
  }
})

export default router
