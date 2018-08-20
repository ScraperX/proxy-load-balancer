# WIP: Proxy Load Balancer


## Running
Find out what args can be passed in: `python run.py -h`

## Config file
Create a `yaml` file to configure the pools and what proxies are in each
Example config file:
```yaml
- Port: 8088
  Host: '0.0.0.0'
  Proxies:
    - Host: proxy1.com
      Port: 80
      User: fooBar
      Pass: 12345
      Types:
        - http
        - https
    - Host: proxy2
      Port: 6000
      Types:
        - http
        - https
- Port: 8089
  Host: '0.0.0.0'
  Proxies:
    - Host: proxy3
      Port: 80
      User: fooBar
      Pass: 12345
      Types:
        - http
        - https

```
