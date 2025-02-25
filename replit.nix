{pkgs}: {
  deps = [
    pkgs.chromium
    pkgs.glibcLocales
    pkgs.geckodriver
    pkgs.postgresql
    pkgs.openssl
  ];
}
