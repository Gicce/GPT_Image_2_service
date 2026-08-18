import axios from 'axios'

const BASE = import.meta.env.VITE_API_BASE || ''

const http = axios.create({ baseURL: BASE })

http.interceptors.request.use(cfg => {
  const token = localStorage.getItem('admin_token')
  if (token) cfg.headers.Authorization = `Bearer ${token}`
  return cfg
})

http.interceptors.response.use(r => r, err => {
  // 登录接口自身的 401（密码错误）与 429（限流）不触发全局登出重定向，
  // 否则整页刷新会销毁登录页上的错误提示
  const url = err.config?.url || ''
  const isLoginRequest = url.includes('/api/auth/admin/login')
  if (!isLoginRequest && err.response?.status === 401) {
    localStorage.removeItem('admin_token')
    location.href = '/admin/'
  }
  return Promise.reject(err)
})

export default http
