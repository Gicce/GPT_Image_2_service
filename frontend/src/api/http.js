import axios from 'axios'

const BASE = import.meta.env.VITE_API_BASE || ''

const http = axios.create({ baseURL: BASE })

http.interceptors.request.use(cfg => {
  const token = localStorage.getItem('admin_token')
  if (token) cfg.headers.Authorization = `Bearer ${token}`
  return cfg
})

http.interceptors.response.use(r => r, err => {
  if (err.response?.status === 401) {
    localStorage.removeItem('admin_token')
    location.href = '/admin/'
  }
  return Promise.reject(err)
})

export default http
