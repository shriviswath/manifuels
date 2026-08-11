await sha256('mynewpassword') 

update users set password_hash = '8f4e2a91c7b3...'
where username = 'shriviswath';
