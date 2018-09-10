# WIP: Proxy Load Balancer


## Running
Find out what args can be passed in: `python run.py -h`

## Config file
Create a `yaml` file to configure the pools and what proxies are in each
Example config file:
```yaml
Server:
  Host: 0.0.0.0
  Port: 8686

Rules:
  - Name: Foo1
    Domains:
      - httpbin.org
    Pools:
      - One
      - Two

  - Name: Bar2
    Domains:
      - api.ipify.org
    Pools:
      - Two

Pools:
  - Name: One
    Proxies:
      - Host: proxy-a.com
        Port: 80
        User: user_a
        Pass: pass_a
        Types:
          - http
          - https
      - Host: proxy-b.com
        Port: 80
        User: user_b
        Pass: pass_b
        Types:
          - http
          - https

  - Name: Two
    Proxies:
      - Host: proxy-c.com
        Port: 80
        User: user_c
        Pass: pass_c
        Types:
          - http
          - https


```
