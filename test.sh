docker run -dt -v /home/ntust-foxlink/foxlink-v9-1/foxlink-api-backend:/code/ \
--env-file /home/ntust-foxlink/foxlink-v9-1/foxlink-api-backend/.env \
-p 8080:80 \
--network incubator-network \
--name incubator-ruby \
incubator:init \
bash

