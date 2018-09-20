# WIP: Proxy Load Balancer


## Running
Pass in your config file to start the servers: `python run.py -c your_config.yaml`

## Config file
Create a `yaml` file to configure the pools and what proxies are in each
Example config file:
```yaml
Server:
  Host: 0.0.0.0  # Optional, Default: 0.0.0.0
  API: 8181  # Optional, Default: 8181
  Log_Requests: true  # Optional, Default: true

Rules:
  - Name: Any domain
    Port: 8989
    Domains:
      - .*
    Pools:
      - Set A

  - Name: Foo1
    Port: 8686
    Domains:
      - httpbin.org
    Pools:
      - Set A
      - Set B

  - Name: Bar2
    Port: 8686
    Domains:
      - api.ipify.org
    Pools:
      - Set B

Pools:
  - Name: Set A
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

  - Name: Set B
    Proxies:
      - Host: proxy-c.com
        Port: 80
        User: user_c
        Pass: pass_c
        Types:
          - http
          - https
```

## Api
**TODO**  
The plan is to have an api wher you can:
- Add/remove proxies from pools
- Add/remove/modify rules
- Access what the current rules/pools are
- Access stats about each request that is passed through the proxy

The idea is that the changes made will be reflected in real time.  
In the mean time, the `yaml` file needs to be updated and the server restarted for any changes to take affect.
