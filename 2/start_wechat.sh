#!/bin/bash
# 杀微信
killall -9 wechat WeChatAppEx crashpad_handler 2>/dev/null
sleep 2
sudo umount -l /tmp/.mount_WeChat* 2>/dev/null
rm -rf ~/.xwechat/lock && mkdir -p ~/.xwechat/lock
touch /tmp/wx_keys.log && chmod 666 /tmp/wx_keys.log

# 编译 LD_PRELOAD 注入器（如果不存在）
if [ ! -f /tmp/keylog_inject.so ]; then
  cat > /tmp/keylog_inject.c << 'CEOF'
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <dlfcn.h>
#define KEYLOG_PATH "SSLKEYLOGFILE=/tmp/wx_keys.log"
#define SELF_PRELOAD "LD_PRELOAD=/tmp/keylog_inject.so"
static char ** inject_env(char *const envp[]) {
    int n = 0;
    int has_ssl = 0, has_preload = 0;
    while (envp[n]) {
        if (strncmp(envp[n], "SSLKEYLOGFILE=", 14) == 0) has_ssl = 1;
        if (strncmp(envp[n], "LD_PRELOAD=", 11) == 0) has_preload = 1;
        n++;
    }
    int extra = (has_ssl ? 0 : 1) + (has_preload ? 0 : 1);
    char **new_envp = (char**)malloc((n + extra + 1) * sizeof(char*));
    int j = 0;
    for (int i = 0; i < n; i++) {
        if (strncmp(envp[i], "SSLKEYLOGFILE=", 14) == 0 && envp[i][14] == '\0') continue;
        new_envp[j++] = envp[i];
    }
    if (!has_ssl) new_envp[j++] = (char*)KEYLOG_PATH;
    if (!has_preload) new_envp[j++] = (char*)SELF_PRELOAD;
    new_envp[j] = NULL;
    return new_envp;
}
int execve(const char *path, char *const argv[], char *const envp[]) {
    static int (*real)(const char *, char *const[], char *const[]) = NULL;
    if (!real) real = dlsym(RTLD_NEXT, "execve");
    return real(path, argv, (char *const*)inject_env(envp));
}
int execvpe(const char *file, char *const argv[], char *const envp[]) {
    static int (*real)(const char *, char *const[], char *const[]) = NULL;
    if (!real) real = dlsym(RTLD_NEXT, "execvpe");
    return real(file, argv, (char *const*)inject_env(envp));
}
int unsetenv(const char *name) {
    if (name && strcmp(name, "SSLKEYLOGFILE") == 0) return 0;
    static int (*real)(const char *) = NULL;
    if (!real) real = dlsym(RTLD_NEXT, "unsetenv");
    return real(name);
}
int clearenv(void) {
    char *val = getenv("SSLKEYLOGFILE");
    char saved[512] = "";
    if (val) snprintf(saved, sizeof(saved), "%s", val);
    static int (*real)(void) = NULL;
    if (!real) real = dlsym(RTLD_NEXT, "clearenv");
    int rc = real();
    if (saved[0]) setenv("SSLKEYLOGFILE", saved, 1);
    return rc;
}
CEOF
  gcc -shared -fPIC -o /tmp/keylog_inject.so /tmp/keylog_inject.c -ldl
fi

# 用 LD_PRELOAD 注入器启动微信
LD_PRELOAD=/tmp/keylog_inject.so SSLKEYLOGFILE=/tmp/wx_keys.log \
  nohup /home/hetaisheng/.local/opt/wechat/current/WeChatLinux_x86_64.AppImage > /tmp/wx_with_keylog.log 2>&1 &
disown
echo "✅ 微信已启动（LD_PRELOAD execve hook），请扫码登录"
echo "   所有 WeChatAppEx 子进程都会强制带 SSLKEYLOGFILE"
