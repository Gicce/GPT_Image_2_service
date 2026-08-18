# client-updates — CyImagePro 客户端更新官方镜像

此目录由 Nginx 挂载至 `/var/www/client-updates:ro`，通过
`https://www.zjcypc.com/client-updates/` 对外分发（无需登录，安全性依赖客户端内置
公钥的 minisign 验签，而非业务 JWT）。

## 目录结构

```
client-updates/
├── latest.json                      # 官方 updater manifest（platforms.*.url 必须指向 www.zjcypc.com）
└── v4.0.3/
    ├── CyImagePro_4.0.3_x64-setup.exe        # 与 GitHub Release 资产 byte-for-byte 一致
    ├── CyImagePro_4.0.3_x64-setup.exe.sig
    ├── CyImagePro_4.0.3_x64_en-US.msi
    └── CyImagePro_4.0.3_x64_en-US.msi.sig
```

## 纪律（不可违反）

1. 安装包与 `.sig` 必须与对应 GitHub Release 资产 **byte-for-byte 一致**（SHA256 相同），
   禁止重新打包、重新签名或修改任何字节。
2. `latest.json` 的 `version` / `pub_date` / `signature` 必须与同一次 CI 构建的
   GitHub manifest 完全一致，仅 `url` 指向官方镜像。
3. 此目录内容**不由 git 分发**（二进制不入库）；正常更新只能由 Release workflow
   （GitHub Actions）自动上传，或按其相同校验步骤手动补传。
4. 已发布版本的产物不可覆盖；发现产物损坏时删除整个版本目录后重新完整上传。
